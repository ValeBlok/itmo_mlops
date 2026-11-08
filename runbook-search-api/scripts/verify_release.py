"""External semantic smoke test for a deployed Helm release.

Opens `kubectl port-forward` to the release Service, reads /meta and runs a
known query. The release is rejected (exit code 1) if the top result is not
the expected document or /meta does not match the expected deployment.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_QUERY = "как вернуть предыдущую модель после плохого релиза"
DEFAULT_TOP = "doc-rollback"


def get_json(url: str, timeout: float = 5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def wait_ready(base_url: str, process: subprocess.Popen, attempts: int = 60) -> dict:
    last_error: Exception | None = None
    for _ in range(attempts):
        if process.poll() is not None:
            raise RuntimeError(f"kubectl port-forward exited with code {process.returncode}")
        try:
            return get_json(f"{base_url}/readyz", timeout=2)
        except Exception as error:  # noqa: BLE001 - retry until ready
            last_error = error
            time.sleep(0.5)
    raise RuntimeError(f"service did not become ready: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--namespace", default="mlops-students")
    parser.add_argument("--port", type=int, default=18090)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--expected-top", default=DEFAULT_TOP)
    parser.add_argument("--request-id", default=f"smoke-{int(time.time())}")
    parser.add_argument("--expect-digest")
    parser.add_argument("--expect-environment")
    parser.add_argument("--expect-ranking-mode")
    parser.add_argument("--output", type=Path, help="write the smoke evidence JSON here")
    args = parser.parse_args()

    base_url = f"http://127.0.0.1:{args.port}"
    process = subprocess.Popen(
        ["kubectl", "-n", args.namespace, "port-forward", f"service/{args.release}-mlops-search", f"{args.port}:80"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    evidence: dict = {"release": args.release, "namespace": args.namespace, "query": args.query}
    failures: list[str] = []
    try:
        evidence["readyz"] = wait_ready(base_url, process)
        meta = get_json(f"{base_url}/meta")
        evidence["meta"] = meta

        payload = json.dumps({"query": args.query, "limit": 3}).encode()
        request = urllib.request.Request(
            f"{base_url}/v1/search",
            data=payload,
            headers={"content-type": "application/json", "x-request-id": args.request_id},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            search = json.load(response)
        evidence["search"] = search

        top = search["results"][0]["id"] if search.get("results") else None
        evidence["top_result"] = top
        if top != args.expected_top:
            failures.append(f"semantic check: expected top result {args.expected_top!r}, got {top!r}")
        if search.get("request_id") != args.request_id:
            failures.append(f"request id was not propagated: {search.get('request_id')!r}")
        if args.expect_digest and meta.get("image_digest") != args.expect_digest:
            failures.append(f"/meta image_digest {meta.get('image_digest')!r} != {args.expect_digest!r}")
        if args.expect_environment and meta.get("environment") != args.expect_environment:
            failures.append(f"/meta environment {meta.get('environment')!r} != {args.expect_environment!r}")
        if args.expect_ranking_mode and meta.get("ranking_mode") != args.expect_ranking_mode:
            failures.append(f"/meta ranking_mode {meta.get('ranking_mode')!r} != {args.expect_ranking_mode!r}")
    except Exception as error:  # noqa: BLE001 - any error rejects the release
        failures.append(f"smoke error: {error}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    evidence["passed"] = not failures
    evidence["failures"] = failures
    rendered = json.dumps(evidence, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    if failures:
        for failure in failures:
            print(f"SEMANTIC SMOKE FAILED: {failure}", file=sys.stderr)
        return 1
    print(f"SEMANTIC SMOKE PASSED: {args.release} top={args.expected_top}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
