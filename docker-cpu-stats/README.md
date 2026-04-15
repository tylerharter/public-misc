# Docker CPU% Inflation under Steal Time

`docker stats` computes CPU% by dividing a container's cgroup CPU usage by the host's `/proc/stat` "cpu" line -- but it only sums fields 1-7 (user through softirq), **excluding field 8 (steal)**. This shrinks the denominator on overcommitted VMs where the hypervisor is stealing cycles, causing reported CPU% to inflate beyond what the container is actually getting.

`cpu_demo.py` demonstrates this by reading both the cgroup usage and `/proc/stat` directly, then showing two percentages side by side:

- **CPU%** -- calculated the way Docker does it (fields 1-7 only)
- **fixed%** -- calculated with steal included (fields 1-8)

On a VM with significant steal time, CPU% will read noticeably higher than fixed%, showing how Docker's numbers can be misleading.
