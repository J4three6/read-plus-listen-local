"""Discover the devices the installed CTranslate2 backend can use."""
from dataclasses import dataclass
import os
import shutil
import subprocess

from media import configure_cuda_dlls, _no_console


@dataclass(frozen=True)
class Device:
    kind: str
    index: int
    compute_type: str
    name: str = ''

    @property
    def label(self):
        return 'CPU' if self.kind == 'cpu' else f'GPU {self.index}' + (f' · {self.name}' if self.name else '')


def nvidia_names():
    binary = shutil.which('nvidia-smi')
    if not binary or 'CUDA_VISIBLE_DEVICES' in os.environ or os.environ.get('CUDA_DEVICE_ORDER') != 'PCI_BUS_ID':
        return []
    try:
        result = subprocess.run([binary, '--query-gpu=pci.bus_id,name', '--format=csv,noheader'],
                                capture_output=True, text=True, check=True, timeout=5, **_no_console())
        return [line.split(',', 1)[1].strip() for line in sorted(result.stdout.splitlines()) if ',' in line]
    except (OSError, subprocess.SubprocessError):
        return []


def available_devices():
    os.environ.setdefault('CUDA_DEVICE_ORDER', 'PCI_BUS_ID')
    import ctranslate2

    devices = []
    notes = []
    try:
        cpu_types = ctranslate2.get_supported_compute_types('cpu')
        if cpu_types:
            devices.append(Device('cpu', 0, 'int8' if 'int8' in cpu_types else 'float32'))
    except (RuntimeError, ValueError, OSError) as exc:
        notes.append(f'CPU: {exc}')

    try:
        count = ctranslate2.get_cuda_device_count()
        if count:
            configure_cuda_dlls()
    except (RuntimeError, ValueError, OSError) as exc:
        notes.append(f'CUDA: {exc}')
        return devices, notes

    names = nvidia_names() if count else []
    for index in range(count):
        try:
            types = ctranslate2.get_supported_compute_types('cuda', index)
            compute = next((kind for kind in ('float16', 'int8_float16', 'int8_float32', 'float32')
                            if kind in types), None)
            if compute:
                name = names[index] if len(names) == count else ''
                devices.append(Device('cuda', index, compute, name))
        except (RuntimeError, ValueError, OSError) as exc:
            notes.append(f'GPU {index}: {exc}')
    return devices, notes
