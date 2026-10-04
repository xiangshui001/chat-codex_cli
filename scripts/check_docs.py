"""Check current installation examples and links without calling GitHub or model APIs."""
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codex-github-local-v2/src"))
from codex_github_local_v2.model_api import ModelRegistry
from codex_github_local_v2.mvp2_contract import DesktopConfig


class Guide(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.external_assets = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag in {"script", "img", "iframe", "link"} and (attrs.get("src") or attrs.get("href")):
            self.external_assets.append(attrs.get("src") or attrs.get("href"))


def main():
    documents = [ROOT / name for name in ("README.md", "AGENTS.md", "web/app/README.md",
                                         "web/app/NOTICE.md", "codex-github-local-v2/README.md")]
    documents += list((ROOT / "docs").rglob("*.md")) + list((ROOT / "history").rglob("*.md"))
    for document in documents:
        source = document.read_text(encoding="utf-8")
        for href in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", source):
            url = urlsplit(href)
            if url.scheme or not url.path or href.startswith("/"):
                continue
            destination = (document.parent / unquote(url.path)).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                raise AssertionError(f"Broken link: {document.relative_to(ROOT)} -> {href}")

    parser = Guide()
    page = (ROOT / "docs/使用指南.html").read_text(encoding="utf-8")
    parser.feed(page)
    assert len(parser.ids) == len(set(parser.ids)), "Duplicate HTML IDs"
    for href in parser.links:
        if href.startswith("#"):
            assert href[1:] in parser.ids, href
    assert not parser.external_assets, parser.external_assets
    assert {"account-owner", "host-id", "hub-repo", "target-repo"}.issubset(parser.ids)

    install = (ROOT / "docs/安装说明.md").read_text(encoding="utf-8")
    generator = re.search(r"<<'PY'\n([\s\S]+?)\nPY", install).group(1)
    with tempfile.TemporaryDirectory() as directory:
        runtime = Path(directory).resolve() / "private"
        result = subprocess.run([sys.executable, "-c", generator, str(runtime), "sample-owner", "laptop"],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        config = DesktopConfig.load(runtime / "config.json")
        assert config.owner == "sample-owner" and config.host_id == "laptop"
        assert config.hub_repo == "sample-owner/codex-cli"
        registry = ModelRegistry(runtime / "models.json")
        registry.validate({"mode": "gpt", "primary": {"provider": "codex", "model": "gpt-example",
                                                    "effort": "low"}}, cli=True)
        before = {name: (runtime / name).read_bytes() for name in ("config.json", "models.json", "service.env")}
        again = subprocess.run([sys.executable, "-c", generator, str(runtime), "different-owner", "other-host"],
                               capture_output=True, text=True)
        assert again.returncode != 0
        assert all((runtime / name).read_bytes() == content for name, content in before.items())
        example = json.loads((ROOT / "codex-github-local-v2/examples/mvp2-config.example.json").read_text())
        example.update(owner="sample-owner", hub_repo="sample-owner/codex-cli",
                       workspace_root=str(runtime / "workspaces"), state_dir=str(runtime / "state"),
                       models_file=str(runtime / "models.json"))
        (runtime / "example.json").write_text(json.dumps(example), encoding="utf-8")
        DesktopConfig.load(runtime / "example.json")
    models = ModelRegistry(ROOT / "codex-github-local-v2/examples/models.example.json")
    for provider, entry in models.providers.items():
        for effort in entry["effort_map"]:
            models.validate({"mode": "gpt" if entry["kind"] == "gpt" else "api",
                             "primary": {"provider": provider, "model": entry["models"][0], "effort": effort}},
                            require_keys=False)
    print(f"Validated {len(documents)} Markdown documents, offline HTML, config generator and current examples")


if __name__ == "__main__":
    main()
