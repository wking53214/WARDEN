"""Operating-system limits for a seat that runs in its own process (Linux only).

`apply` is called inside the seat's process, before any seat code is imported. It cannot be undone from
inside that process. What it sets:

  - no new privileges, so nothing the seat starts can gain rights;
  - Landlock file rules: the process can read the Python installation, the system folders it needs, the
    folders it was told to read (the governed repository, the seat's own code), and write only in its
    scratch folder. Everywhere else is closed to it, including the rest of the home folder;
  - a seccomp filter that refuses to create or use a network socket, and refuses io_uring, ptrace and reading
    another process's memory, so the file rules cannot be reached around;
  - size limits: no core file, a cap on the largest file it may write, on open files, on memory and on CPU.

`unavailable()` says why this machine cannot give those limits, or None when it can. Warden refuses to run
a seat in this mode when it returns a reason, never runs the seat unprotected instead.

What this does not do: it does not stop a seat from burning its CPU allowance, from reading what it was
allowed to read, or from starting more processes of its own (they inherit every rule above). It is a floor
for a seat that is checked code, not a promise against a determined attacker with a kernel exploit.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import resource
import struct
import sys
from pathlib import Path
from typing import Iterable, Optional

# -- Landlock ---------------------------------------------------------------------------------------

_SYS_LANDLOCK = {"x86_64": (444, 445, 446), "aarch64": (444, 445, 446)}
_ACCESS = {  # name -> (bit, first ABI version that has it)
    "execute": (1 << 0, 1), "write_file": (1 << 1, 1), "read_file": (1 << 2, 1), "read_dir": (1 << 3, 1),
    "remove_dir": (1 << 4, 1), "remove_file": (1 << 5, 1), "make_char": (1 << 6, 1), "make_dir": (1 << 7, 1),
    "make_reg": (1 << 8, 1), "make_sock": (1 << 9, 1), "make_fifo": (1 << 10, 1), "make_block": (1 << 11, 1),
    "make_sym": (1 << 12, 1), "refer": (1 << 13, 2), "truncate": (1 << 14, 3), "ioctl_dev": (1 << 15, 5),
}
_FILE_RIGHTS = {"execute", "write_file", "read_file", "truncate", "ioctl_dev"}
_RULE_PATH_BENEATH = 1

# -- seccomp ----------------------------------------------------------------------------------------

_AUDIT_ARCH = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}
#: Calls that create or use a network socket, reach around the file rules, or read another process.
_DENIED = {
    "x86_64": {"socket": 41, "connect": 42, "accept": 43, "sendto": 44, "recvfrom": 45, "sendmsg": 46,
               "recvmsg": 47, "bind": 49, "listen": 50, "socketpair": 53, "ptrace": 101,
               "process_vm_readv": 310, "process_vm_writev": 311, "accept4": 288, "recvmmsg": 299,
               "sendmmsg": 307, "io_uring_setup": 425, "io_uring_enter": 426, "io_uring_register": 427},
    "aarch64": {"socket": 198, "socketpair": 199, "bind": 200, "listen": 201, "accept": 202, "connect": 203,
                "sendto": 206, "recvfrom": 207, "sendmsg": 211, "recvmsg": 212, "accept4": 242,
                "recvmmsg": 243, "ptrace": 117, "process_vm_readv": 270, "process_vm_writev": 271,
                "sendmmsg": 269, "io_uring_setup": 425, "io_uring_enter": 426, "io_uring_register": 427},
}
_BPF_LD_W_ABS, _BPF_JEQ_K, _BPF_JGE_K, _BPF_RET_K = 0x20, 0x15, 0x35, 0x06
_SECCOMP_RET_ALLOW, _SECCOMP_RET_ERRNO, _SECCOMP_RET_KILL = 0x7FFF0000, 0x00050000, 0x80000000
_PR_SET_NO_NEW_PRIVS, _PR_SET_SECCOMP, _SECCOMP_MODE_FILTER = 38, 22, 2
_EPERM = 1

#: Folders a Python seat needs to start at all. Only those that exist are used.
_SYSTEM_READ = ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", "/proc", "/dev", "/opt")


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def _prctl(option: int, a2: int = 0, a3: int = 0, a4: int = 0, a5: int = 0) -> int:
    """prctl with every argument as a full-width integer, so an address is not cut to 32 bits."""
    libc = _libc()
    libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
    libc.prctl.restype = ctypes.c_int
    return libc.prctl(option, a2, a3, a4, a5)


def _landlock_abi() -> int:
    numbers = _SYS_LANDLOCK.get(platform.machine())
    if numbers is None:
        return 0
    version = _libc().syscall(numbers[0], None, 0, 1)  # LANDLOCK_CREATE_RULESET_VERSION
    return int(version) if version > 0 else 0


def unavailable() -> Optional[str]:
    """Why this machine cannot give a seat the limits above, or None when it can."""
    if not sys.platform.startswith("linux"):
        return f"seat isolation needs Linux, and this is {sys.platform}"
    machine = platform.machine()
    if machine not in _AUDIT_ARCH:
        return f"seat isolation has no rules for the {machine} processor"
    if _landlock_abi() < 1:
        return "this kernel does not offer Landlock file rules (Linux 5.13 or later with Landlock turned on)"
    return None


def python_read_paths() -> list[str]:
    """The folders a Python process needs to read to run: its own installation and the system folders."""
    found: list[str] = []
    for place in (sys.prefix, sys.base_prefix, sys.exec_prefix, *_SYSTEM_READ):
        if place and os.path.exists(place):
            found.append(os.path.realpath(place))
    return found


def _rules(read: Iterable[str], write: Iterable[str], abi: int) -> list[tuple[str, int]]:
    supported = {name for name, (_, first) in _ACCESS.items() if first <= abi}
    read_rights = {"execute", "read_file", "read_dir"} & supported
    write_rights = supported - {"execute"}
    out: dict[str, set[str]] = {}
    for path in read:
        out.setdefault(os.path.realpath(path), set()).update(read_rights)
    for path in write:
        out.setdefault(os.path.realpath(path), set()).update(read_rights | write_rights)
    rules = []
    for path, rights in out.items():
        if not os.path.exists(path):
            continue
        if not os.path.isdir(path):
            rights = rights & _FILE_RIGHTS
        rules.append((path, sum(_ACCESS[r][0] for r in rights)))
    return rules


def _landlock(read: Iterable[str], write: Iterable[str]) -> None:
    libc = _libc()
    create, add, restrict = _SYS_LANDLOCK[platform.machine()]
    abi = _landlock_abi()
    handled = sum(bit for _, (bit, first) in _ACCESS.items() if first <= abi)
    attr = struct.pack("<Q", handled)
    fd = libc.syscall(create, attr, len(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "Landlock: the ruleset could not be created")
    try:
        for path, rights in _rules(read, write, abi):
            path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = struct.pack("<Qi", rights, path_fd)  # packed, 12 bytes: u64 allowed_access, s32 parent_fd
                if libc.syscall(add, fd, _RULE_PATH_BENEATH, rule, 0) != 0:
                    raise OSError(ctypes.get_errno(), f"Landlock: the rule for {path} could not be added")
            finally:
                os.close(path_fd)
        if libc.syscall(restrict, fd, 0) != 0:
            raise OSError(ctypes.get_errno(), "Landlock: the rules could not be applied")
    finally:
        os.close(fd)


#: What a suite needs to talk to its own children over a pair of unnamed local sockets (asyncio's event loop does).
#: Creating a named or network socket stays refused, so none of this reaches another machine or a socket file.
_SOCKETPAIR_IO = frozenset({"socketpair", "sendto", "recvfrom", "sendmsg", "recvmsg", "sendmmsg", "recvmmsg"})


def _seccomp(allow_socketpair: bool = False) -> None:
    machine = platform.machine()
    denied = sorted(number for name, number in _DENIED[machine].items()
                    if not (allow_socketpair and name in _SOCKETPAIR_IO))
    ins = [(_BPF_LD_W_ABS, 0, 0, 4)]  # load the architecture
    ins.append((_BPF_JEQ_K, 1, 0, _AUDIT_ARCH[machine]))
    ins.append((_BPF_RET_K, 0, 0, _SECCOMP_RET_KILL))  # a call from another architecture is refused outright
    ins.append((_BPF_LD_W_ABS, 0, 0, 0))  # load the call number
    if machine == "x86_64":  # the x32 call table has other numbers for the same calls, so none of it is allowed
        ins.append((_BPF_JGE_K, 0, 1, 0x40000000))
        ins.append((_BPF_RET_K, 0, 0, _SECCOMP_RET_KILL))
    for number in denied:
        ins.append((_BPF_JEQ_K, 0, 1, number))
        ins.append((_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO | _EPERM))
    ins.append((_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW))
    blob = b"".join(struct.pack("HBBI", code, jt, jf, k) for code, jt, jf, k in ins)
    buffer = ctypes.create_string_buffer(blob, len(blob))
    prog = struct.pack("HxxxxxxP", len(ins), ctypes.addressof(buffer))
    prog_buf = ctypes.create_string_buffer(prog, len(prog))
    if _prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.addressof(prog_buf)) != 0:
        raise OSError(ctypes.get_errno(), "seccomp: the filter could not be installed")


def _limits(cpu_seconds: Optional[int], memory_bytes: Optional[int], file_bytes: int, open_files: int) -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    wanted = min(open_files, hard) if hard != resource.RLIM_INFINITY else open_files
    resource.setrlimit(resource.RLIMIT_NOFILE, (wanted, wanted))
    if memory_bytes:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    if cpu_seconds:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))


def apply(*, read: Iterable[str], scratch: str, cpu_seconds: Optional[int],
          memory_bytes: Optional[int] = 4 << 30, write: Iterable[str] = (), allow_socketpair: bool = False,
          file_bytes: int = 64 << 20, open_files: int = 256) -> None:
    """Close the process in. Raises OSError, and the caller must stop, if any rule could not be set.

    `write` names further folders the process may write in, beside its scratch folder. `memory_bytes=None`
    sets no memory cap (a test suite may legitimately need a lot). `allow_socketpair` lets the process make
    pairs of unnamed local sockets; it still cannot create any other socket.
    """
    reason = unavailable()
    if reason:
        raise OSError(reason)
    if _prctl(_PR_SET_NO_NEW_PRIVS, 1) != 0:
        raise OSError(ctypes.get_errno(), "no_new_privs could not be set")
    _limits(cpu_seconds, memory_bytes, file_bytes, open_files)
    _landlock([*read, *python_read_paths()],
              [scratch, *write, *(p for p in ("/dev/null",) if Path(p).exists())])
    _seccomp(allow_socketpair)


def exec_main() -> None:
    """Close this process in as `sys.argv[1]` (JSON) says, then become the program it names.

    Used to start a target's test suite: the limits survive the exec, so the suite and everything it
    starts runs under them. Never returns on success.
    """
    request = json.loads(sys.argv[1])
    apply(read=request["read"], scratch=request["scratch"], write=request["write"], cpu_seconds=None,
          memory_bytes=None, allow_socketpair=True, file_bytes=1 << 30, open_files=4096)
    os.execve(request["argv"][0], request["argv"], request["env"])
