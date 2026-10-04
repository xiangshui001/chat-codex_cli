#!/usr/bin/env python3
"""Register a dedicated local clone. Never run models, push, or create issues."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

import bridge


def install(profile_path, destination=None):
    if os.name != "posix":
        raise bridge.Halt("Use Ubuntu/WSL for this setup")
    for name in ("git", "gh", "codex"):
        if not shutil.which(name):
            raise bridge.Halt(name + " is missing from PATH")
    profile = bridge.core.read_json(profile_path)
    repository = profile["repository"]
    if not bridge.re.fullmatch(bridge.REPO_RE, repository):
        raise bridge.Halt("Invalid repository")
    api = bridge.GitHub()
    user = api.api("user")
    if user["login"].lower() not in {x.lower() for x in profile["authorized_users"]}:
        raise bridge.Halt("Log gh into the authorized repository account first")
    remote = api.api("repos/" + repository)
    if not remote.get("permissions", {}).get("push") or not remote.get("has_issues"):
        raise bridge.Halt("Repository push/issue access is missing")
    if remote.get("default_branch") != profile["base_branch"] or remote.get("archived"):
        raise bridge.Halt("Repository base branch/status differs from the profile")

    installed = Path.home() / ".local/share/codex-github-local/0.1.0"
    # Install executable components only; test logs and future profile files are
    # mutable evidence/configuration, not part of the versioned runtime.
    files = [bridge.BUNDLE / "bridge.py", bridge.BUNDLE / "handoff_check.py"]
    files += [p for p in (bridge.BUNDLE / "engine").rglob("*")
              if p.is_file() and "__pycache__" not in p.parts]
    if installed.exists():
        for path in files:
            target = installed / path.relative_to(bridge.BUNDLE)
            if not target.is_file() or target.read_bytes() != path.read_bytes():
                raise bridge.Halt("Installed version differs; retain it and use a separately versioned update")
    else:
        for path in files:
            target = installed / path.relative_to(bridge.BUNDLE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())

    launcher = Path.home() / ".local/bin/codex-github-local"
    script = "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(installed / "bridge.py")) + ' "$@"\n'
    if launcher.exists() and launcher.read_text() != script:
        raise bridge.Halt("A different launcher exists; preserved it. Run the installed bridge.py directly")
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(script)
    launcher.chmod(0o700)

    key = repository.replace("/", "__")
    project = bridge.APP / "repos" / key
    project.mkdir(parents=True, exist_ok=True)
    cfg_path = project / "config.json"
    if cfg_path.exists():
        b = bridge.Bridge(cfg_path)
        print(json.dumps(bridge.doctor(b), ensure_ascii=False, indent=2))
        print("Already registered; configuration preserved: " + str(cfg_path))
        return
    root = (Path(destination).expanduser() if destination else
            Path.home() / "codex-workspaces" / repository).resolve()
    marker = project / "clone-in-progress.json"
    if root.exists() and not (marker.is_file() and bridge.core.read_json(marker).get("root") == str(root)):
        raise bridge.Halt("Clone destination already exists; it was not overwritten. Choose a new --root")
    marker_data = {"repository": repository, "root": str(root)}
    if not root.exists():
        bridge.core.write_json(marker, marker_data)
        root.parent.mkdir(parents=True, exist_ok=True)
        bridge.shell(["git", "-c", "credential.helper=", "-c",
                      "credential.https://github.com.helper=!gh auth git-credential",
                      "clone", "--branch", profile["base_branch"],
                      f"https://github.com/{repository}.git", str(root)])
    origin = bridge.shell(["git", "remote", "get-url", "origin"], root)
    if origin != f"https://github.com/{repository}.git":
        raise bridge.Halt("Clone origin mismatch")
    if bridge.shell(["git", "status", "--porcelain"], root):
        raise bridge.Halt("Dedicated clone is not clean")
    bridge.shell(["git", "config", "--local", "user.name", user["login"]], root)
    bridge.shell(["git", "config", "--local", "user.email",
                  f"{user['id']}+{user['login']}@users.noreply.github.com"], root)
    profile.update(root=str(root), runtime=str(project / "runtime"),
                   codex_command=[str(Path(shutil.which("codex")).resolve())])
    for check in profile["checks"].values():
        check["argv"] = [x.replace("{bundle}", str(installed)) for x in check["argv"]]
    bridge.core.write_json(cfg_path, profile)
    marker.unlink(missing_ok=True)

    print(json.dumps(bridge.doctor(bridge.Bridge(cfg_path)), ensure_ascii=False, indent=2))
    print("Registered. No task executed and no remote writes performed.")
    print("Start after the offline tests pass: " + str(launcher) + " watch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=bridge.BUNDLE / "profiles/example.json")
    parser.add_argument("--root")
    options = parser.parse_args()
    try:
        install(options.profile, options.root)
    except (bridge.Halt, OSError, ValueError, KeyError) as exc:
        print("Setup stopped: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
