# Support matrix

What has actually been run, on what, and with what result. "Tested" means a recorded run of
`scripts/installer-smoke.sh` (a clean install, `econosim desktop --check`, `econosim doctor`, an upgrade that
keeps your results, a window on a virtual X11 display, an uninstall) on a fresh machine.

| System | Architecture | Python | Display | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| Ubuntu 24.04 | x86-64 | 3.12 | X11 on Xvfb | **supported, tested** (GitHub-hosted fresh VM) | `installer-smoke` workflow |
| Debian 12 | x86-64 | 3.11 | X11 on Xvfb | **tested, one step pending**: install, checks, upgrade and uninstall ran in a fresh container; the Xvfb window step failed once because the container lacked `xauth` (a test-environment gap, since added) and has not yet re-run | `installer-smoke` workflow |
| Ubuntu 22.04 | x86-64 | 3.10 | n/a | **not supported**: the installer refuses cleanly, because the project needs Python 3.11 or newer | `installer-smoke` workflow |
| Other Debian/Ubuntu releases | x86-64 | 3.11+ | | expected to work, **not tested** | none |
| Other distributions | | | | not tested | none |
| Wayland | | | | **not tested** | none |
| Arm (aarch64) | | | | **not tested**; the CPU PyTorch wheel exists, nothing was run | none |
| Windows, macOS | | | | not supported for jobs (they need Linux); the web demo runs anywhere | none |
| A physical display, a real menu and a desktop icon | | | | observed only on the maintainer's machine | none |

The runs happen on every change to the installer, the desktop code or the lock, and weekly
(`.github/workflows/installer-smoke.yml`), because a base image or a dependency can change under an unchanged
repository. Qt needs `libxcb-cursor0` on X11 (`sudo apt install libxcb-cursor0`); the application names it when it is
missing. GPU: the installer installs the CPU build of PyTorch and every lab runs on it; CUDA is not validated.
Network: the install downloads PyTorch and other dependencies, so it is not an offline installer; once installed the
labs run offline because the datasets are committed.
