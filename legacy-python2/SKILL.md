---
name: legacy-python2
description: Run old Python 2.7 code, such as a 2008–2015 Django app or library, to reproduce a bug or verify a fix before changing it. Use when a repository predates Python 3 and you need to execute it rather than judge it by reading.
---

# Running Python 2.7 code and old Django releases

Verified on 2026-11-06 while fixing akaihola/django-wtform.

## What works

[scripts/py2run.sh](scripts/py2run.sh) runs a script with Python 2.7.18 and a
chosen Django release in a throwaway container with no network:

```bash
legacy-python2/scripts/py2run.sh 1.4.22 path/to/repo check.py
```

- The repository is mounted read-only at `/code`, which is also the working
  directory. Django and the repository are on `PYTHONPATH`; nothing is installed.
- The first run of a release downloads its source into `~/.cache/py2run/`.
- Exit status is the script's own, so a check can fail loudly.
- A standalone check calls `settings.configure()`, and on Django 1.7 and
  later also `django.setup()`, before importing forms or models.

The script ran Django 1.0.4 and 1.4.22. The same image and mounts, run by
hand, also loaded 1.1.4, 1.8.19 and 1.9.13. Django 1.11.29 stops at
`ImportError: No module named pytz`; the script does not fetch other
dependencies.

## Facts that cost time

- **nixpkgs has no Python 2.** Current nixpkgs removed `python27`. The
  nixos-24.05 package set still has it, but marked insecure and not built by
  Hydra, so `nix-shell -p python27` compiles CPython from source. That is
  CPU-heavy work for the build machine, not a laptop; use the container instead.
- **The container image** is `docker.io/library/python:2.7-alpine`
  (Python 2.7.18, built 2020-04-20); podman pulls it on first use. Override
  it with `PY2RUN_IMAGE`.
- **PyPI has no files for Django before 1.1.4.** Django 1.0.x tarballs come from
  `https://www.djangoproject.com/download/<version>/tarball/`, which redirects
  to the real file. The script handles this; the 1.1.0–1.1.3 branch is
  untested.
- **Django 1.9 removed `SortedDict`**, so code importing it runs only up to 1.8.
- Podman needs the Bash sandbox disabled.
