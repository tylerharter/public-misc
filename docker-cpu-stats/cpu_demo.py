import os, subprocess, time
from collections import namedtuple

INTERVAL = 1

Container = namedtuple("Container", ["full_id", "name"])
Snapshot = namedtuple("Snapshot", ["cgroup_ns", "system_ns", "steal_ns"])
SystemCPU = namedtuple("SystemCPU", ["system_ns", "steal_ns", "ncpus"])

def get_containers():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}} {{.Names}}"],
        capture_output=True, text=True
    )
    containers = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        short_id, name = line.split(None, 1)
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.Id}}", short_id],
            capture_output=True, text=True
        )
        containers.append(Container(r.stdout.strip(), name))
    return containers

def read_cgroup_cpu_ns(full_id):
    with open(f"/sys/fs/cgroup/system.slice/docker-{full_id}.scope/cpu.stat") as f:
        for line in f:
            if line.startswith("usage_usec"):
                return int(line.split()[1]) * 1000
    return 0

def read_system_cpu():
    """Docker sums /proc/stat fields 1-7 only, EXCLUDING steal (field 8).
    See moby/moby daemon/stats_unix.go readSystemCPUUsage()."""
    ncpus = 0
    with open("/proc/stat") as f:
        for line in f:
            parts = line.split()
            if parts[0] == "cpu":
                system_jiffies = sum(int(x) for x in parts[1:8])
                steal_jiffies = int(parts[8])
            elif parts[0].startswith("cpu"):
                ncpus += 1
            else:
                break
    return SystemCPU(system_jiffies * 10_000_000, steal_jiffies * 10_000_000, ncpus)

def snapshot(container):
    sys = read_system_cpu()
    cg = read_cgroup_cpu_ns(container.full_id)
    return Snapshot(cg, sys.system_ns, sys.steal_ns), sys.ncpus

def main():
    containers = get_containers()
    assert containers, "no running containers"
    prev = {c.full_id: snapshot(c)[0] for c in containers}

    for _ in range(5):
        time.sleep(INTERVAL)

        print(f"{'CONTAINER':<20} {'cg usage_usec':>14} {'/proc/stat 1-7':>16} {'1-8':>16} {'CPU%':>8} {'fixed%':>8}")
        print(f"{'':20} {'(ms)':>14} {'(ms)':>16} {'(ms)':>16}")
        print("-" * 86)

        total_pct = 0
        total_fixed = 0
        for c in containers:
            cur, ncpus = snapshot(c)
            old = prev[c.full_id]

            cg_delta = cur.cgroup_ns - old.cgroup_ns
            sys_delta = cur.system_ns - old.system_ns
            steal_delta = cur.steal_ns - old.steal_ns
            fixed_delta = sys_delta + steal_delta

            pct = (cg_delta / sys_delta) * ncpus * 100 if sys_delta else 0
            fixed_pct = (cg_delta / fixed_delta) * ncpus * 100 if fixed_delta else 0
            total_pct += pct
            total_fixed += fixed_pct

            print(f"{c.name:<20} {cg_delta/1e6:>14.1f} {sys_delta/1e6:>16.1f} {fixed_delta/1e6:>16.1f} {pct:>7.1f}% {fixed_pct:>7.1f}%")
            prev[c.full_id] = cur

        steal_pct = steal_delta / fixed_delta * 100 if fixed_delta else 0
        print("-" * 86)
        print(f"{'TOTAL':<20} {'':>14} {'':>16} {'':>16} {total_pct:>7.1f}% {total_fixed:>7.1f}%")
        print(f"steal: {steal_pct:.0f}%  |  real cpu: {(1-steal_pct/100)*ncpus:.1f}/{ncpus} cores")
        print()

    print("/proc/stat 'cpu' line fields:")
    print("- 1. user:    time running user-space code")
    print("- 2. nice:    time running niced (low-priority) user-space code")
    print("- 3. system:  time running kernel code")
    print("- 4. idle:    time doing nothing")
    print("- 5. iowait:  time idle while waiting on I/O")
    print("- 6. irq:     time handling hardware interrupts")
    print("- 7. softirq: time handling software interrupts")
    print("- 8. steal:   time the hypervisor ran a different VM instead of us")
    print()
    print("Docker sums 1-7 only. Excluding steal shrinks the denominator,")
    print("so CPU% inflates when the VM is overcommitted.")

if __name__ == "__main__":
    main()
