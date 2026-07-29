"""
Server data collector — CPU, RAM, disk, Docker, network info.
"""

import os
import shutil
from datetime import datetime, timedelta

import psutil

# ── CPU ──────────────────────────────────────────

def cpu_percent() -> float:
    return psutil.cpu_percent(interval=1)


def cpu_count() -> dict:
    return {"physical": psutil.cpu_count(logical=False), "logical": psutil.cpu_count(logical=True)}


def cpu_temp() -> str:
    """CPU temperature (Linux only, via thermal zone)."""
    try:
        paths = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/hwmon/hwmon0/temp1_input",
        ]
        for p in paths:
            if os.path.exists(p):
                with open(p) as f:
                    return f"{int(f.read().strip()) / 1000:.1f}°C"
    except Exception:
        pass
    return "N/A"


# ── RAM ──────────────────────────────────────────

def ram_info() -> dict:
    mem = psutil.virtual_memory()
    return {
        "total_gb": round(mem.total / (1024**3), 1),
        "used_gb": round(mem.used / (1024**3), 1),
        "available_gb": round(mem.available / (1024**3), 1),
        "percent": mem.percent,
    }


def swap_info() -> dict:
    sw = psutil.swap_memory()
    return {
        "total_gb": round(sw.total / (1024**3), 1),
        "used_gb": round(sw.used / (1024**3), 1),
        "percent": sw.percent,
    }


# ── DISK ─────────────────────────────────────────

HOST_ROOT = "/host_root"


def disk_info() -> list[dict]:
    """Read disk info. When inside a container, read from HOST_ROOT."""
    result = []

    use_host = os.path.isdir(HOST_ROOT)
    mounts_file = f"{HOST_ROOT}/proc/mounts" if use_host else "/proc/mounts"

    REAL_FS = {"ext4", "ext3", "ext2", "xfs", "btrfs", "zfs", "ntfs", "vfat", "fuseblk"}
    FUSE_PREFIX = "fuse."  # fuse.rclone, fuse.sshfs, etc.

    seen = set()
    with open(mounts_file) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3:
                continue
            device, mountpoint, fstype = parts[0], parts[1], parts[2]

            # Only real filesystems or FUSE
            if fstype not in REAL_FS and not fstype.startswith(FUSE_PREFIX):
                continue
            # Skip Docker overlay lower dirs
            if "docker/rootfs" in mountpoint:
                continue
            # Skip /boot
            if mountpoint.endswith("/boot") or mountpoint.endswith("/boot/efi"):
                continue
            # Skip non-essential bind mounts (Docker utilities, etc.)
            SKIP_PREFIXES = (
                "/usr/local/libexec/docker",
                "/usr/local/bin/docker",
            )
            if mountpoint.startswith(SKIP_PREFIXES):
                continue
            # When reading from host proc, mountpoint is already prefixed with /host_root
            path = mountpoint if use_host else f"{HOST_ROOT}{mountpoint}"
            if not os.path.isdir(path):
                continue
            if mountpoint in seen:
                continue
            seen.add(mountpoint)

            try:
                usage = shutil.disk_usage(path)
                display_mount = mountpoint.replace(HOST_ROOT, "") if use_host else mountpoint
                display_mount = display_mount or "/"  # root
                result.append({
                    "mount": display_mount,
                    "device": device,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                    "percent": round(usage.used / usage.total * 100, 1),
                })
            except (PermissionError, FileNotFoundError, ZeroDivisionError):
                continue

    return result


# ── NETWORK ──────────────────────────────────────

def net_info() -> dict:
    """IP addresses + Tailscale status."""
    info = {}
    addrs = psutil.net_if_addrs()
    for iface, addr_list in addrs.items():
        if iface == "lo":
            continue
        for addr in addr_list:
            if addr.family == 2:  # AF_INET
                info[iface] = addr.address

    info["tailscale"] = _tailscale_ip()
    return info


def _tailscale_ip() -> str:
    # Try via interface (network_mode: host makes tailscale0 visible)
    addrs = psutil.net_if_addrs()
    for name in ("tailscale0", "tailscale"):
        if name in addrs:
            for addr in addrs[name]:
                if addr.family == 2:  # AF_INET
                    return addr.address
    # Fallback: CLI
    try:
        out = os.popen("tailscale ip -4 2>/dev/null").read().strip()
        return out if out else "not running"
    except Exception:
        return "not installed"


# ── UPTIME ───────────────────────────────────────

def uptime_info() -> dict:
    boot = datetime.fromtimestamp(psutil.boot_time())
    now = datetime.now()
    delta = now - boot

    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes = rem // 60

    return {
        "boot_time": boot.strftime("%Y-%m-%d %H:%M"),
        "uptime": f"{days}d {hours}h {minutes}m",
    }


# ── DOCKER ───────────────────────────────────────

import docker as _docker_mod

_docker_client = None


def _get_docker():
    global _docker_client
    if _docker_client is None:
        try:
            _docker_client = _docker_mod.from_env()
        except Exception:
            return None
    return _docker_client


def docker_containers() -> list[dict]:
    """List all containers + status via Docker SDK."""
    client = _get_docker()
    if client is None:
        return []

    try:
        all_containers = client.containers.list(all=True)
    except Exception:
        return []

    containers = []
    for c in all_containers:
        status = c.status  # 'running', 'exited', 'paused', etc.
        if status == "running":
            short = "🟢 Up"
        elif status == "exited":
            short = "🔴 Stopped"
        else:
            short = f"🟡 {status}"

        image_tags = c.image.tags
        image = image_tags[0] if image_tags else c.image.short_id

        # Detect compose project from label
        project = c.labels.get("com.docker.compose.project", "")
        if not project:
            # Fallback: group by name prefix (npm-app → npm)
            project = _guess_project(c.name)

        containers.append({
            "name": c.name,
            "status": short,
            "image": image,
            "project": project,
        })

    return containers


def _guess_project(name: str) -> str:
    """Guess project name from container name."""
    # Pattern: project-suffix → e.g. npm-app → npm, myporto-db → myporto
    parts = name.rsplit("-", 1)
    if len(parts) == 2 and parts[1] in ("app", "db", "webserver", "phpmyadmin", "backend", "frontend"):
        return parts[0]
    return name


def docker_groups() -> dict[str, list[dict]]:
    """Group containers by project."""
    containers = docker_containers()
    groups: dict[str, list[dict]] = {}
    for c in containers:
        p = c.get("project", "other")
        groups.setdefault(p, []).append(c)
    return groups


# ── DOCKER CONTROL ────────────────────────────────

def docker_restart(container: str) -> tuple[bool, str]:
    client = _get_docker()
    if client is None:
        return (False, "Docker not accessible")
    try:
        c = client.containers.get(container)
        c.restart()
        return (True, "OK")
    except Exception as e:
        return (False, str(e))


def docker_stop(container: str) -> tuple[bool, str]:
    client = _get_docker()
    if client is None:
        return (False, "Docker not accessible")
    try:
        c = client.containers.get(container)
        c.stop()
        return (True, "OK")
    except Exception as e:
        return (False, str(e))


def docker_start(container: str) -> tuple[bool, str]:
    client = _get_docker()
    if client is None:
        return (False, "Docker not accessible")
    try:
        c = client.containers.get(container)
        c.start()
        return (True, "OK")
    except Exception as e:
        return (False, str(e))


def docker_group_compose(project: str, compose_cmd: str) -> tuple[bool, str]:
    """Run docker compose <cmd> in the project directory."""
    import subprocess

    workdir = docker_group_workdir(project)
    if not workdir:
        return (False, f"Working directory not found for '{project}'")

    try:
        result = subprocess.run(
            ["docker", "compose", compose_cmd],
            cwd=workdir, capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return (True, result.stdout.strip()[-500:] or "OK")
        else:
            return (False, result.stderr.strip()[-500:] or result.stdout.strip()[-500:])
    except subprocess.TimeoutExpired:
        return (False, "Timeout (>1 min)")
    except Exception as e:
        return (False, str(e))


def docker_group_restart(project: str) -> tuple[bool, str]:
    return docker_group_compose(project, "restart")


def docker_group_stop(project: str) -> tuple[bool, str]:
    return docker_group_compose(project, "stop")


def docker_group_start(project: str) -> tuple[bool, str]:
    return docker_group_compose(project, "start")


def docker_group_down(project: str) -> tuple[bool, str]:
    return docker_group_compose(project, "down")


def docker_group_workdir(group: str) -> str | None:
    """Get compose working directory from container labels."""
    groups = docker_groups()
    if group not in groups:
        return None
    client = _get_docker()
    if client is None:
        return None
    for c in groups[group]:
        try:
            cont = client.containers.get(c["name"])
            wd = cont.labels.get("com.docker.compose.project.working_dir")
            if wd:
                return wd
        except Exception:
            continue
    return None


def docker_group_rebuild(group: str) -> tuple[bool, str]:
    """docker compose up -d --build."""
    import subprocess

    workdir = docker_group_workdir(group)
    if not workdir:
        return (False, f"Working directory not found for '{group}'")

    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "--build"],
            cwd=workdir, capture_output=True, text=True, timeout=180
        )
        if result.returncode == 0:
            return (True, result.stdout.strip()[-500:] or "OK")
        else:
            return (False, result.stderr.strip()[-500:] or result.stdout.strip()[-500:])
    except subprocess.TimeoutExpired:
        return (False, "Timeout (>3 min)")
    except Exception as e:
        return (False, str(e))


def docker_group_recreate(group: str) -> tuple[bool, str]:
    """docker compose up -d (pull + recreate)."""
    import subprocess

    workdir = docker_group_workdir(group)
    if not workdir:
        return (False, f"Working directory not found for '{group}'")

    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=workdir, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return (True, result.stdout.strip()[-500:] or "OK")
        else:
            return (False, result.stderr.strip()[-500:] or result.stdout.strip()[-500:])
    except subprocess.TimeoutExpired:
        return (False, "Timeout (>2 min)")
    except Exception as e:
        return (False, str(e))


def docker_group_has_dockerfile(group: str) -> bool:
    """Check if project has a Dockerfile (build context)."""
    workdir = docker_group_workdir(group)
    if not workdir:
        return False
    # Container needs /host_root prefix to access host filesystem
    path = f"{HOST_ROOT}{workdir}/Dockerfile" if os.path.isdir(HOST_ROOT) else f"{workdir}/Dockerfile"
    return os.path.isfile(path)


# ── TOP PROCESSES ────────────────────────────────

def top_processes(count: int = 5) -> list[dict]:
    """Top N processes by CPU usage."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            info["cpu_percent"] = info["cpu_percent"] or 0
            info["memory_percent"] = round(info["memory_percent"] or 0, 1)
            procs.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
    return procs[:count]


# ── SUMMARY ──────────────────────────────────────

def full_status() -> dict:
    return {
        "cpu": {
            "percent": cpu_percent(),
            "count": cpu_count(),
            "temp": cpu_temp(),
        },
        "ram": ram_info(),
        "swap": swap_info(),
        "disk": disk_info(),
        "network": net_info(),
        "uptime": uptime_info(),
        "docker": {
            "total": len(docker_containers()),
            "running": len([c for c in docker_containers() if c["status"].startswith("🟢")]),
            "stopped": len([c for c in docker_containers() if c["status"].startswith("🔴")]),
        },
    }
