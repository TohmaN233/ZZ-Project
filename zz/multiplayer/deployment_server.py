from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence

from zz.multiplayer.deployment import (
    DeploymentConfig,
    DeploymentConfigError,
    build_deployment_runtime,
)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="ZZ authoritative multiplayer deployment server"
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate environment and print a non-sensitive summary without binding ports",
    )
    args = parser.parse_args(argv)

    try:
        config = DeploymentConfig.from_environ(os.environ if environ is None else environ)
    except DeploymentConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.check_config:
        print(json.dumps(config.summary(), sort_keys=True, separators=(",", ":")))
        return 0

    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(message)s",
    )
    build_deployment_runtime(config).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
