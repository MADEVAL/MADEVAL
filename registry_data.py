#!/usr/bin/env python3
"""Build one registry-data.json for the profile repository.

Sources: GitHub (MADEVAL + GLOBUS-studio), npm, Packagist, WordPress.org,
crates.io, PyPI, pub.dev. No secrets are written to the output.
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "registry-data.json"
UA = "MADEVAL-registry-data/1.0 (+https://github.com/MADEVAL/MADEVAL)"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
REGISTRIES = ["Packagist", "crates.io", "WordPress.org", "NPM", "PyPI", "pub.dev"]
TIMEOUT = 30


def get_json(url: str, headers: dict | None = None):
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (403, 429) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last  # type: ignore[misc]


def github_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def github_repos(endpoint: str, repo_type: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        sep = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{sep}type={repo_type}&per_page=100&page={page}&sort=updated"
        data = get_json(url, github_headers())
        if not isinstance(data, list) or not data:
            break
        for repo in data:
            if repo.get("fork") or repo.get("archived"):
                continue
            if repo.get("name") == ".github" or repo.get("full_name") == "MADEVAL/MADEVAL":
                continue
            out.append({
                "key": f"github:{repo['full_name']}",
                "title": repo["name"],
                "full_name": repo["full_name"],
                "description": repo.get("description") or "",
                "language": repo.get("language") or "",
                "stars": int(repo.get("stargazers_count") or 0),
                "url": repo["html_url"],
                "pushed_at": repo.get("pushed_at") or "",
            })
        if len(data) < 100:
            break
        page += 1
    return out


def npm_packages() -> list[dict]:
    data = get_json(
        "https://registry.npmjs.org/-/v1/search?text=maintainer:yevhen-leonidov&size=250"
    )
    out = []
    for item in data.get("objects", []):
        pkg = item.get("package", {})
        out.append({
            "registry": "NPM",
            "key": f"npm:{pkg.get('name', '')}",
            "title": pkg.get("name", ""),
            "description": pkg.get("description") or "",
            "version": pkg.get("version") or "",
            "downloads": int((item.get("downloads") or {}).get("monthly") or 0),
            "metric": "downloads/mo",
            "url": "https://www.npmjs.com/package/" + pkg.get("name", ""),
        })
    return out


def latest_stable_version(versions: dict) -> str:
    latest = ""
    normalized = ""
    for value in versions.values():
        version = str(value.get("version") or "")
        if "dev" in version:
            continue
        candidate = str(value.get("version_normalized") or "")
        if candidate > normalized:
            normalized = candidate
            latest = version
    return latest


def packagist_packages() -> list[dict]:
    data = get_json("https://packagist.org/users/Yevhen%20Leonidov/packages.json")
    out = []
    for item in data.get("packages", []):
        name = item.get("name") or ""
        if not name:
            continue
        try:
            pkg = get_json(f"https://packagist.org/packages/{name}.json").get("package", {})
            out.append({
                "registry": "Packagist",
                "key": f"packagist:{name}",
                "title": name,
                "description": pkg.get("description") or item.get("description") or "",
                "version": latest_stable_version(pkg.get("versions") or {}),
                "downloads": int((pkg.get("downloads") or {}).get("total") or 0),
                "metric": "downloads",
                "url": "https://packagist.org/packages/" + name,
            })
        except Exception as exc:  # noqa: BLE001
            print(f"Packagist {name}: {exc}", file=sys.stderr)
    return out


def wordpress_packages() -> list[dict]:
    out = []
    page = 1
    while True:
        url = (
            "https://api.wordpress.org/plugins/info/1.2/"
            "?action=query_plugins&request%5Bauthor%5D=globusstudio"
            f"&request%5Bper_page%5D=100&request%5Bpage%5D={page}"
        )
        data = get_json(url)
        plugins = data.get("plugins") or []
        for plugin in plugins:
            slug = plugin.get("slug") or ""
            if not slug:
                continue
            out.append({
                "registry": "WordPress.org",
                "key": f"wp:{slug}",
                "title": html.unescape(plugin.get("name") or slug),
                "description": html.unescape(plugin.get("short_description") or ""),
                "version": plugin.get("version") or "",
                "downloads": int(plugin.get("active_installs") or 0),
                "metric": "installs",
                "url": "https://wordpress.org/plugins/" + slug + "/",
            })
        pages = int((data.get("info") or {}).get("pages") or 1)
        if page >= pages:
            break
        page += 1
    return out


def crates_packages() -> list[dict]:
    # MADEVAL on crates.io, user id 428683.
    data = get_json("https://crates.io/api/v1/crates?user_id=428683&per_page=100")
    out = []
    for crate in data.get("crates", []):
        name = crate.get("name") or ""
        if not name:
            continue
        out.append({
            "registry": "crates.io",
            "key": f"crates:{name}",
            "title": name,
            "description": crate.get("description") or "",
            "version": crate.get("max_version") or "",
            "downloads": int(crate.get("downloads") or 0),
            "metric": "downloads",
            "url": "https://crates.io/crates/" + name,
        })
    return out


def pypi_packages() -> list[dict]:
    names: list[str] = []
    try:
        client = xmlrpc.client.ServerProxy("https://pypi.org/pypi")
        names = sorted({pkg for _role, pkg in client.user_packages("GLOBUS.studio")})
    except Exception as exc:  # noqa: BLE001
        print(f"PyPI user_packages: {exc}", file=sys.stderr)
    if not names:
        names = ["readsight"]
    out = []
    for name in names:
        pkg = get_json(f"https://pypi.org/pypi/{name}/json").get("info", {})
        downloads = 0
        try:
            stats = get_json(f"https://pypistats.org/api/packages/{name}/recent")
            downloads = int((stats.get("data") or {}).get("last_month") or 0)
        except Exception as exc:  # noqa: BLE001
            print(f"PyPI stats {name}: {exc}", file=sys.stderr)
        out.append({
            "registry": "PyPI",
            "key": f"pypi:{name}",
            "title": name,
            "description": pkg.get("summary") or "",
            "version": pkg.get("version") or "",
            "downloads": downloads,
            "metric": "downloads/mo",
            "url": f"https://pypi.org/project/{name}/",
        })
    return out


def pub_packages() -> list[dict]:
    data = get_json("https://pub.dev/api/search?q=publisher%3Aleonidov.dev")
    out = []
    for item in data.get("packages", []):
        name = item.get("package") or ""
        if not name:
            continue
        pkg = get_json(f"https://pub.dev/api/packages/{name}")
        try:
            score = get_json(f"https://pub.dev/api/packages/{name}/score")
        except Exception:  # noqa: BLE001
            score = {}
        latest = pkg.get("latest") or {}
        pubspec = latest.get("pubspec") or {}
        out.append({
            "registry": "pub.dev",
            "key": f"pub:{name}",
            "title": name,
            "description": pubspec.get("description") or "",
            "version": latest.get("version") or "",
            "downloads": int(score.get("downloadCount30Days") or 0),
            "metric": "downloads/30d",
            "url": f"https://pub.dev/packages/{name}",
        })
    return out


def main() -> int:
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            old = {}

    errors: list[str] = []
    stale: list[str] = []

    try:
        repos = github_repos("https://api.github.com/users/MADEVAL/repos", "owner")
        org_repos = github_repos("https://api.github.com/orgs/GLOBUS-studio/repos", "public")
        repos.extend(org_repos)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"GitHub: {exc}")
        repos = old.get("github") or []
        stale.append("GitHub")
    repos.sort(key=lambda r: (-int(r.get("stars") or 0), r.get("title", "").lower()))

    sources = {
        "Packagist": packagist_packages,
        "crates.io": crates_packages,
        "WordPress.org": wordpress_packages,
        "NPM": npm_packages,
        "PyPI": pypi_packages,
        "pub.dev": pub_packages,
    }
    packages: list[dict] = []
    for registry in REGISTRIES:
        try:
            items = sources[registry]()
            if not items and old.get("packages"):
                previous = [p for p in old["packages"] if p.get("registry") == registry]
                if previous:
                    raise RuntimeError("empty response")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{registry}: {exc}")
            items = [p for p in (old.get("packages") or []) if p.get("registry") == registry]
            stale.append(registry)
        items.sort(key=lambda p: (-int(p.get("downloads") or 0), p.get("title", "").lower()))
        packages.extend(items)

    totals = {}
    for registry in REGISTRIES:
        items = [p for p in packages if p.get("registry") == registry]
        totals[registry] = {
            "count": len(items),
            "downloads": sum(int(p.get("downloads") or 0) for p in items),
            "metric": items[0].get("metric", "") if items else "",
        }
    totals["GitHub"] = {"count": len(repos), "stars": sum(int(r.get("stars") or 0) for r in repos)}

    payload = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "ok": not errors,
        "errors": errors,
        "stale": sorted(set(stale)),
        "github": repos,
        "packages": packages,
        "totals": totals,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"registry-data.json: {len(repos)} repos, {len(packages)} packages, "
        f"errors={len(errors)}, stale={sorted(set(stale))}"
    )
    for error in errors:
        print(f"WARN {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
