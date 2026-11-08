import argparse
import json
import time
import urllib.request


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    args = parser.parse_args()

    for _ in range(30):
        try:
            ready = get_json(f"{args.base_url}/readyz")
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("service did not become ready")

    payload = json.dumps({
        "query": "как вернуть предыдущую модель после плохого релиза",
        "limit": 3,
    }).encode()
    request = urllib.request.Request(
        f"{args.base_url}/v1/search",
        data=payload,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        search = json.load(response)
    if search["results"][0]["id"] != "doc-rollback":
        raise SystemExit(f"unexpected ranking: {search}")
    print(json.dumps({"ready": ready, "search": search}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
