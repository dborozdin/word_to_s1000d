"""
Application version.
Major/minor set manually. Build number = git commit count.
"""
MAJOR = 1
MINOR = 0


def _get_build_number() -> int:
    """Get build number from git commit count. Returns 0 if git unavailable."""
    import subprocess
    try:
        result = subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    # Fallback: read from bundled _build_number file (frozen mode)
    import os
    from app_paths import get_internal_root
    build_file = os.path.join(get_internal_root(), '_build_number')
    if os.path.isfile(build_file):
        with open(build_file) as f:
            return int(f.read().strip())
    return 0


BUILD = _get_build_number()
__version__ = f'{MAJOR}.{MINOR}.{BUILD}'
