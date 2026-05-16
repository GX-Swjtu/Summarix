from __future__ import annotations

import argparse
import base64
import getpass
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = ROOT / "deploy"
BACKEND_COMPOSE = DEPLOY_DIR / "backend" / "compose.yml"
PLG_COMPOSE = DEPLOY_DIR / "plg" / "compose.yml"
LANGWATCH_DIR = DEPLOY_DIR / "langwatch"
LANGWATCH_COMPOSE = LANGWATCH_DIR / "compose.yml"
SHARED_COMPOSE = DEPLOY_DIR / "shared" / "compose.yml"
RUNTIME_DIR = DEPLOY_DIR / "runtime"
GENERATED_ENV = RUNTIME_DIR / "monitoring.generated.env"
DATA_DIR = DEPLOY_DIR / "data"
ROOT_ENV = ROOT / ".env"
ROOT_ENV_EXAMPLE = ROOT / ".env.example"
API_KEY_ENV = ROOT / ".env.api.key"
API_KEY_ENV_EXAMPLE = ROOT / ".env.api.key.example"
LANGWATCH_ENV = LANGWATCH_DIR / ".env"
LANGWATCH_ENV_EXAMPLE = LANGWATCH_DIR / ".env.example"
PERSISTED_ENV = RUNTIME_DIR / "monitoring.persisted.env"
LANGWATCH_TLS_CA_CERT_DEFAULT = "../runtime/langwatch/tls/ca.crt"
LANGWATCH_TLS_CA_KEY_DEFAULT = "../runtime/langwatch/tls/ca.key"
LANGWATCH_TLS_CERT_DEFAULT = "../runtime/langwatch/tls/tls.crt"
LANGWATCH_TLS_KEY_DEFAULT = "../runtime/langwatch/tls/tls.key"

INVALID_SECRET_VALUES = {
    "",
    "change-me-in-.env",
    "please-change-this-secret",
    "please_please_please_change_me_asap",
    "change-me-to-a-random-string",
    "change me to a random string",
    "0000000000000000000000000000000000000000000000000000000000000000",
}
URL_HOST_PATTERN = re.compile(r"^[a-zA-Z0-9+]+://(?:[^@/]+@)?([^:/?]+)")
MODEL_PROVIDER_KEY_NAMES = {
    "DASHSCOPE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
}
API_KEY_FILE_KEYS = [
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_API_BASE",
    "LANGWATCH_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "VERTEXAI_PROJECT",
    "VERTEXAI_LOCATION",
]
LANGWATCH_BOOTSTRAP_ORG_NAME = "Summarix Local"
LANGWATCH_BOOTSTRAP_ORG_SLUG = "summarix-local"
LANGWATCH_BOOTSTRAP_TEAM_NAME = "Summarix Team"
LANGWATCH_BOOTSTRAP_TEAM_SLUG = "summarix-local-team"
LANGWATCH_BOOTSTRAP_PROJECT_NAME = "Summarix Monitoring"
LANGWATCH_BOOTSTRAP_PROJECT_SLUG = "summarix-monitoring"
DEFAULT_BACKEND_HOST_PORT = "8000"
BACKEND_HOST_PORT_FALLBACKS = tuple(str(port) for port in range(18000, 18010))
TRUTHY_VALUES = {"1", "true", "yes", "on"}


class CheckError(RuntimeError):
    pass


def parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 由 scripts/monitoring_stack.py 自动生成，请勿手动编辑。"]
    lines.extend(f"{key}={value}" for key, value in values.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def upsert_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = False
    for index, raw_line in enumerate(lines):
        if raw_line.strip().startswith(f"{key}="):
            lines[index] = f"{key}={value}"
            updated = True
            break
    if not updated:
        if not lines:
            lines.append("# 首次由 scripts/monitoring_stack.py 自动生成，请按需继续维护。")
        lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_env_files(*paths: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for path in paths:
        data.update(parse_env_file(path))
    return data


def env_value(name: str, file_values: dict[str, str], default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    value = file_values.get(name)
    if value not in (None, ""):
        return value
    return default


def file_value(name: str, file_values: dict[str, str], default: str | None = None) -> str | None:
    value = file_values.get(name)
    if value not in (None, ""):
        return value
    return default


def env_flag_enabled(name: str, file_values: dict[str, str], default: str = "false") -> bool:
    value = env_value(name, file_values, default) or default
    return value.strip().lower() in TRUTHY_VALUES


def host_port_available(port: str) -> bool:
    try:
        port_number = int(port)
    except (TypeError, ValueError):
        return False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port_number))
        except OSError:
            return False
    return True


def select_backend_host_port(file_values: dict[str, str]) -> str:
    explicit_port = env_value("SUMMARIX_BACKEND_PORT", file_values)
    if explicit_port:
        return explicit_port

    candidates = (DEFAULT_BACKEND_HOST_PORT, *BACKEND_HOST_PORT_FALLBACKS)
    for candidate in candidates:
        if host_port_available(candidate):
            return candidate

    raise CheckError(f"未找到可用的后端宿主端口，请显式设置 SUMMARIX_BACKEND_PORT。已尝试: {', '.join(candidates)}")


def monitoring_langwatch_enabled() -> str:
    value = os.environ.get("LANGWATCH_ENABLED")
    if value not in (None, ""):
        return value
    return "true"


def is_strong_secret(value: str | None) -> bool:
    return bool(value) and value not in INVALID_SECRET_VALUES and len(value) >= 32


def generate_secret() -> str:
    return secrets.token_urlsafe(48)


def first_non_empty(*values: str | None, default: str) -> str:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def first_strong_secret(*values: str | None) -> str | None:
    for value in values:
        if is_strong_secret(value):
            return value
    return None


def run_command(
    cmd: list[str],
    *,
    capture: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=False,
        env=env,
        input=input_text,
    )
    if check and result.returncode != 0:
        stderr_text = (result.stderr or "").strip()
        stdout_text = (result.stdout or "").strip()
        message = stderr_text or stdout_text or f"命令失败: {' '.join(cmd)}"
        raise CheckError(message)
    return result


def ensure_docker_ready() -> None:
    if shutil.which("docker") is None:
        raise CheckError("未找到 docker 命令，请先安装 Docker Desktop 或 Docker Engine。")
    try:
        run_command(["docker", "compose", "version"], capture=True)
    except CheckError as exc:
        raise CheckError("当前环境不可用 docker compose，请先安装 Docker Compose 插件。") from exc
    try:
        run_command(["docker", "info"], capture=True)
    except CheckError as exc:
        raise CheckError("Docker 守护进程不可用，请先启动 Docker Desktop。") from exc


def compose_command(compose_files: Path | list[Path], *args: str, profiles: list[str] | None = None) -> list[str]:
    files = compose_files if isinstance(compose_files, list) else [compose_files]
    cmd = ["docker", "compose"]
    for compose_file in files:
        cmd.extend(["-f", str(compose_file)])
    for profile in profiles or []:
        cmd.extend(["--profile", profile])
    cmd.extend(args)
    return cmd


def compose_process_env() -> dict[str, str]:
    merged = os.environ.copy()
    for values in (
        parse_env_file(ROOT_ENV),
        parse_env_file(API_KEY_ENV),
        parse_env_file(LANGWATCH_ENV),
        parse_env_file(PERSISTED_ENV),
        parse_env_file(GENERATED_ENV),
    ):
        merged.update(values)
    return merged


def run_compose(
    compose_files: Path | list[Path],
    *args: str,
    profiles: list[str] | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_command(
        compose_command(compose_files, *args, profiles=profiles),
        capture=capture,
        check=check,
        env=compose_process_env(),
    )


def docker_image_exists(image_name: str) -> bool:
    return run_command(["docker", "image", "inspect", image_name], capture=True, check=False).returncode == 0


def backend_image_name(file_values: dict[str, str] | None = None) -> str:
    runtime_values = file_values or effective_runtime_values()
    return env_value("SUMMARIX_BACKEND_IMAGE", runtime_values, "summarix-backend:latest") or "summarix-backend:latest"


def start_backend_stack(file_values: dict[str, str] | None = None) -> None:
    runtime_values = file_values or effective_runtime_values()
    image_name = backend_image_name(runtime_values)
    if env_flag_enabled("SUMMARIX_BACKEND_FORCE_BUILD", runtime_values) or not docker_image_exists(image_name):
        run_compose(BACKEND_COMPOSE, "up", "-d", "--build", "--remove-orphans")
        return

    print(f"检测到本地 backend 镜像 {image_name}，本次跳过 --build；如需强制重建请设置 SUMMARIX_BACKEND_FORCE_BUILD=true。")
    run_compose(BACKEND_COMPOSE, "up", "-d", "--remove-orphans")


def show_logs(compose_files: Path | list[Path]) -> None:
    files = compose_files if isinstance(compose_files, list) else [compose_files]
    for compose_file in files:
        if not compose_file.exists():
            continue
        relative_path = compose_file.relative_to(ROOT).as_posix()
        print(f"最近日志（{relative_path}）：")
        subprocess.run(
            compose_command(compose_file, "logs", "--tail", "40"),
            cwd=ROOT,
            check=False,
            env=compose_process_env(),
        )


def host_from_url(value: str | None) -> str | None:
    if not value:
        return None
    match = URL_HOST_PATTERN.match(value)
    if match:
        return match.group(1)
    if value.startswith("sqlite"):
        return "sqlite"
    return None


def normalize_langwatch_internal_endpoint(value: str | None) -> str | None:
    if not value:
        return None
    host = host_from_url(value)
    if host in {"127.0.0.1", "localhost"}:
        return "http://langwatch:5560"
    return value


def normalize_public_url_for_https(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "http":
        return value
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def is_langwatch_api_key(value: str | None) -> bool:
    return bool(value) and value.startswith("sk-lw-") and len(value) >= 20


def ensure_langwatch_api_key_configured(file_values: dict[str, str] | None = None) -> str | None:
    runtime_values = file_values or effective_runtime_values()
    existing_key = env_value("LANGWATCH_API_KEY", runtime_values)
    if is_langwatch_api_key(existing_key):
        print("已复用现有 LANGWATCH_API_KEY。")
        return existing_key

    public_url = env_value("LANGWATCH_PUBLIC_URL", runtime_values, "https://127.0.0.1:5560") or "https://127.0.0.1:5560"
    print("未检测到 LANGWATCH_API_KEY，接下来将按 LangWatch 官方推荐方式完成接入。")
    print(f"请先在浏览器打开 {public_url}，注册或登录 LangWatch。")
    print(f"登录后请创建或选择一个项目；建议项目名使用 {LANGWATCH_BOOTSTRAP_PROJECT_NAME}，这样后续文档与界面名称一致。")
    print("然后在该项目设置中生成 Project API Key，并把它粘贴回当前终端。")

    if not sys.stdin.isatty():
        print("当前终端不是交互模式，无法隐藏输入 API Key。请把 LANGWATCH_API_KEY 手动写入 .env.api.key 后重新执行 make monitor-up。")
        return None

    while True:
        try:
            api_key = getpass.getpass("请输入 LangWatch Project API Key（输入 skip 可跳过本次 LangWatch trace 接入）: ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise CheckError("LangWatch API Key 输入已取消，请重新执行 make monitor-up 完成官方接入流程。") from exc

        if not api_key:
            print("未输入 API Key，请完成 LangWatch UI 中的项目 Key 生成后再粘贴。")
            continue
        if api_key.lower() == "skip":
            print("已跳过 LangWatch Project API Key 配置；本次启动不会把 Summarix trace 上报到 LangWatch。")
            return None
        if not is_langwatch_api_key(api_key):
            print("输入内容看起来不是 LangWatch Project API Key。LangWatch 项目 Key 通常以 sk-lw- 开头，请重新输入。")
            continue

        upsert_env_value(API_KEY_ENV, "LANGWATCH_API_KEY", api_key)
        print("已将 LANGWATCH_API_KEY 写入 .env.api.key，后续启动会直接复用。")
        return api_key


def resolve_langwatch_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (LANGWATCH_DIR / path).resolve()


def unique_hosts(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        candidate = (value or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            address = sock.getsockname()[0]
            if address:
                addresses.add(address)
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            address = item[4][0]
            if address:
                addresses.add(address)
    except socket.gaierror:
        return []
    return sorted(addresses)


def build_langwatch_tls_hosts(file_values: dict[str, str]) -> list[str]:
    explicit_hosts = [item.strip() for item in (env_value("LANGWATCH_TLS_HOSTS", file_values, "") or "").split(",")]
    public_host = host_from_url(env_value("LANGWATCH_PUBLIC_URL", file_values))
    return unique_hosts(
        [
            public_host,
            "localhost",
            "127.0.0.1",
            socket.gethostname(),
            socket.getfqdn(),
            *explicit_hosts,
            *local_ipv4_addresses(),
        ]
    )


def subject_alt_name_entries(hosts: list[str]) -> str:
    entries: list[str] = []
    for host in hosts:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            entries.append(f"DNS:{host}")
        else:
            entries.append(f"IP:{host}")
    return ",".join(entries)


def generate_langwatch_local_ca(ca_cert_path: Path, ca_key_path: Path) -> None:
    if shutil.which("openssl") is None:
        raise CheckError("未找到 openssl，无法为 LangWatch 自动生成本地 CA。")

    ca_cert_path.parent.mkdir(parents=True, exist_ok=True)
    result = run_command(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "3650",
            "-keyout",
            str(ca_key_path),
            "-out",
            str(ca_cert_path),
            "-subj",
            "/CN=Summarix LangWatch Local CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-addext",
            "subjectKeyIdentifier=hash",
        ],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        raise CheckError(f"自动生成 LangWatch 本地 CA 失败: {error_text}")

    ca_cert_path.chmod(0o644)
    ca_key_path.chmod(0o600)


def generate_langwatch_server_certificate(
    cert_path: Path,
    key_path: Path,
    ca_cert_path: Path,
    ca_key_path: Path,
    hosts: list[str],
) -> None:
    if shutil.which("openssl") is None:
        raise CheckError("未找到 openssl，无法为 LangWatch 自动生成服务器证书。")

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    primary_host = hosts[0] if hosts else "localhost"
    subject_alt_names = subject_alt_name_entries(hosts or ["localhost", "127.0.0.1"])
    with tempfile.TemporaryDirectory(prefix="langwatch-tls-") as tmp_dir:
        csr_path = Path(tmp_dir) / "server.csr"
        extfile_path = Path(tmp_dir) / "server.ext"
        serial_path = Path(tmp_dir) / "langwatch-ca.srl"
        extfile_path.write_text(
            "\n".join(
                [
                    "basicConstraints=critical,CA:FALSE",
                    "keyUsage=critical,digitalSignature,keyEncipherment",
                    "extendedKeyUsage=serverAuth",
                    f"subjectAltName={subject_alt_names}",
                    "authorityKeyIdentifier=keyid,issuer",
                    "subjectKeyIdentifier=hash",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        request_result = run_command(
            [
                "openssl",
                "req",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-keyout",
                str(key_path),
                "-out",
                str(csr_path),
                "-subj",
                f"/CN={primary_host}",
                "-addext",
                f"subjectAltName={subject_alt_names}",
            ],
            capture=True,
            check=False,
        )
        if request_result.returncode != 0:
            error_text = (request_result.stderr or request_result.stdout or "").strip()
            raise CheckError(f"生成 LangWatch 服务器证书请求失败: {error_text}")

        result = run_command(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(csr_path),
                "-CA",
                str(ca_cert_path),
                "-CAkey",
                str(ca_key_path),
                "-CAcreateserial",
                "-CAserial",
                str(serial_path),
                "-out",
                str(cert_path),
                "-days",
                "3650",
                "-sha256",
                "-extfile",
                str(extfile_path),
            ],
            capture=True,
            check=False,
        )
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        raise CheckError(f"自动签发 LangWatch 服务器证书失败: {error_text}")

    cert_path.chmod(0o644)
    key_path.chmod(0o600)


def generate_langwatch_self_signed_certificate(cert_path: Path, key_path: Path, hosts: list[str]) -> None:
    ca_cert_path = resolve_langwatch_path(LANGWATCH_TLS_CA_CERT_DEFAULT)
    ca_key_path = resolve_langwatch_path(LANGWATCH_TLS_CA_KEY_DEFAULT)
    generate_langwatch_local_ca(ca_cert_path, ca_key_path)
    generate_langwatch_server_certificate(cert_path, key_path, ca_cert_path, ca_key_path, hosts)


def ensure_langwatch_tls_assets(file_values: dict[str, str]) -> None:
    cert_file = env_value("LANGWATCH_TLS_CERT_FILE", file_values, LANGWATCH_TLS_CERT_DEFAULT) or LANGWATCH_TLS_CERT_DEFAULT
    key_file = env_value("LANGWATCH_TLS_KEY_FILE", file_values, LANGWATCH_TLS_KEY_DEFAULT) or LANGWATCH_TLS_KEY_DEFAULT
    cert_path = resolve_langwatch_path(cert_file)
    key_path = resolve_langwatch_path(key_file)

    if cert_path.exists() and key_path.exists():
        return
    if cert_path.exists() != key_path.exists():
        raise CheckError("LangWatch TLS 证书与私钥文件必须成对存在，请同时提供或删除后重新生成。")

    hosts = build_langwatch_tls_hosts(file_values)
    generate_langwatch_self_signed_certificate(cert_path, key_path, hosts)
    print(f"已为 LangWatch 生成自签名证书: {cert_path}")


def ensure_file_from_example(target: Path, example: Path, description: str) -> bool:
    if target.exists():
        return False
    if not example.exists():
        raise CheckError(f"缺少 {example.relative_to(ROOT).as_posix()}，无法自动生成 {description}。")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def bootstrap_api_key_env(root_values: dict[str, str], langwatch_values: dict[str, str]) -> bool:
    if API_KEY_ENV.exists():
        return False

    seed_values: dict[str, str] = {}
    for key in API_KEY_FILE_KEYS:
        value = first_non_empty(root_values.get(key), langwatch_values.get(key), default="")
        if value:
            seed_values[key] = value

    if seed_values:
        API_KEY_ENV.write_text(
            "# 首次由 scripts/monitoring_stack.py 从现有配置迁移生成，请按需继续维护。\n"
            + "\n".join(f"{key}={value}" for key, value in seed_values.items())
            + "\n",
            encoding="utf-8",
        )
        return True

    return ensure_file_from_example(API_KEY_ENV, API_KEY_ENV_EXAMPLE, ".env.api.key")


def ensure_runtime_layout() -> None:
    directories = [
        DATA_DIR / "backend" / "artifacts",
        DATA_DIR / "postgres",
        DATA_DIR / "redis",
        DATA_DIR / "plg" / "prometheus",
        DATA_DIR / "plg" / "loki",
        DATA_DIR / "plg" / "grafana",
        DATA_DIR / "langwatch" / "clickhouse",
        RUNTIME_DIR / "langwatch" / "tls",
        RUNTIME_DIR,
    ]
    writable_directories = {
        DATA_DIR / "backend" / "artifacts",
        DATA_DIR / "plg" / "prometheus",
        DATA_DIR / "plg" / "loki",
        DATA_DIR / "plg" / "grafana",
        DATA_DIR / "langwatch" / "clickhouse",
    }
    readable_directories = {
        DEPLOY_DIR / "plg" / "grafana" / "dashboards",
        DEPLOY_DIR / "plg" / "grafana" / "provisioning",
        DEPLOY_DIR / "plg" / "grafana" / "provisioning" / "dashboards",
        DEPLOY_DIR / "plg" / "grafana" / "provisioning" / "datasources",
    }

    def chmod_best_effort(path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except PermissionError:
            return
        except OSError:
            return

    def walk_best_effort(directory: Path):
        def ignore_walk_error(_: OSError) -> None:
            return

        yield from os.walk(directory, onerror=ignore_walk_error)

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        if directory in writable_directories:
            chmod_best_effort(directory, 0o777)
            for root, dir_names, file_names in walk_best_effort(directory):
                chmod_best_effort(Path(root), 0o777)
                for dir_name in dir_names:
                    chmod_best_effort(Path(root) / dir_name, 0o777)
                for file_name in file_names:
                    chmod_best_effort(Path(root) / file_name, 0o666)
    for directory in readable_directories:
        directory.mkdir(parents=True, exist_ok=True)
        chmod_best_effort(directory, 0o755)
        for root, dir_names, file_names in walk_best_effort(directory):
            chmod_best_effort(Path(root), 0o755)
            for dir_name in dir_names:
                chmod_best_effort(Path(root) / dir_name, 0o755)
            for file_name in file_names:
                chmod_best_effort(Path(root) / file_name, 0o644)


def build_persisted_env(
    root_values: dict[str, str],
    langwatch_values: dict[str, str],
    persisted_values: dict[str, str],
) -> dict[str, str]:
    return {
        "SUMMARIX_POSTGRES_DB": first_non_empty(
            persisted_values.get("SUMMARIX_POSTGRES_DB"),
            root_values.get("SUMMARIX_POSTGRES_DB"),
            default="summarix",
        ),
        "SUMMARIX_POSTGRES_USER": first_non_empty(
            persisted_values.get("SUMMARIX_POSTGRES_USER"),
            root_values.get("SUMMARIX_POSTGRES_USER"),
            default="summarix",
        ),
        "SUMMARIX_POSTGRES_PASSWORD": first_non_empty(
            persisted_values.get("SUMMARIX_POSTGRES_PASSWORD"),
            root_values.get("SUMMARIX_POSTGRES_PASSWORD"),
            default=generate_secret(),
        ),
        "JWT_SECRET_KEY": first_strong_secret(
            persisted_values.get("JWT_SECRET_KEY"),
            root_values.get("JWT_SECRET_KEY"),
        )
        or generate_secret(),
        "NEXTAUTH_SECRET": first_strong_secret(
            persisted_values.get("NEXTAUTH_SECRET"),
            langwatch_values.get("NEXTAUTH_SECRET"),
        )
        or generate_secret(),
        "BETTER_AUTH_SECRET": first_strong_secret(
            persisted_values.get("BETTER_AUTH_SECRET"),
            langwatch_values.get("BETTER_AUTH_SECRET"),
        )
        or generate_secret(),
        "CREDENTIALS_SECRET": first_strong_secret(
            persisted_values.get("CREDENTIALS_SECRET"),
            langwatch_values.get("CREDENTIALS_SECRET"),
        )
        or generate_secret(),
        "API_TOKEN_JWT_SECRET": first_strong_secret(
            persisted_values.get("API_TOKEN_JWT_SECRET"),
            langwatch_values.get("API_TOKEN_JWT_SECRET"),
        )
        or generate_secret(),
        "METRICS_API_KEY": first_strong_secret(
            persisted_values.get("METRICS_API_KEY"),
            langwatch_values.get("METRICS_API_KEY"),
        )
        or generate_secret(),
        "GRAFANA_ADMIN_USER": first_non_empty(
            persisted_values.get("GRAFANA_ADMIN_USER"),
            root_values.get("GRAFANA_ADMIN_USER"),
            default="admin",
        ),
        "GRAFANA_ADMIN_PASSWORD": first_non_empty(
            persisted_values.get("GRAFANA_ADMIN_PASSWORD"),
            root_values.get("GRAFANA_ADMIN_PASSWORD"),
            default=generate_secret(),
        ),
    }


def has_any_model_api_key(values: dict[str, str]) -> bool:
    return any(values.get(key) for key in MODEL_PROVIDER_KEY_NAMES)


def effective_runtime_values() -> dict[str, str]:
    return merge_env_files(ROOT_ENV, LANGWATCH_ENV, API_KEY_ENV, PERSISTED_ENV, GENERATED_ENV)


def build_generated_env(
    root_values: dict[str, str],
    langwatch_values: dict[str, str],
    persisted_values: dict[str, str],
    api_key_values: dict[str, str],
) -> dict[str, str]:
    combined_values = dict(root_values)
    combined_values.update(langwatch_values)
    combined_values.update(persisted_values)
    combined_values.update(api_key_values)

    postgres_db = env_value("SUMMARIX_POSTGRES_DB", combined_values, "summarix") or "summarix"
    postgres_user = env_value("SUMMARIX_POSTGRES_USER", combined_values, "summarix") or "summarix"
    postgres_password = env_value("SUMMARIX_POSTGRES_PASSWORD", combined_values, "summarix") or "summarix"
    postgres_port = env_value("SUMMARIX_POSTGRES_PORT", combined_values, "5432") or "5432"
    backend_port = select_backend_host_port(combined_values)
    langwatch_port = env_value("LANGWATCH_PORT", combined_values, "5560") or "5560"
    langwatch_public_url = (
        normalize_public_url_for_https(env_value("LANGWATCH_PUBLIC_URL", combined_values, f"https://127.0.0.1:{langwatch_port}"))
        or f"https://127.0.0.1:{langwatch_port}"
    )
    clickhouse_data_source = (
        "langwatch-clickhouse-data"
        if platform.system() == "Windows"
        else "../data/langwatch/clickhouse"
    )
    default_chat_mode = "adk" if has_any_model_api_key(api_key_values) else "mock"

    generated = {
        "SUMMARIX_POSTGRES_DB": postgres_db,
        "SUMMARIX_POSTGRES_USER": postgres_user,
        "SUMMARIX_POSTGRES_PASSWORD": postgres_password,
        "SUMMARIX_POSTGRES_PORT": postgres_port,
        "SUMMARIX_REDIS_PORT": env_value("SUMMARIX_REDIS_PORT", combined_values, "6379") or "6379",
        "SUMMARIX_BACKEND_PORT": backend_port,
        "PROMETHEUS_PORT": env_value("PROMETHEUS_PORT", combined_values, "9090") or "9090",
        "LOKI_PORT": env_value("LOKI_PORT", combined_values, "3100") or "3100",
        "GRAFANA_PORT": env_value("GRAFANA_PORT", combined_values, "3000") or "3000",
        "GRAFANA_ADMIN_USER": env_value("GRAFANA_ADMIN_USER", combined_values, "admin") or "admin",
        "GRAFANA_ADMIN_PASSWORD": env_value("GRAFANA_ADMIN_PASSWORD", combined_values, "please-change-me") or "please-change-me",
        "LANGWATCH_PORT": langwatch_port,
        "DATABASE_URL": f"postgresql+asyncpg://{postgres_user}:{postgres_password}@postgres:5432/{postgres_db}",
        "ADK_DATABASE_URL": f"postgresql+asyncpg://{postgres_user}:{postgres_password}@postgres:5432/{postgres_db}",
        "DATABASE_AUTO_CREATE_DATABASE": "false",
        "DATABASE_AUTO_CREATE_TABLES": env_value("DATABASE_AUTO_CREATE_TABLES", combined_values, "true") or "true",
        "PROMETHEUS_ENABLED": "true",
        "PROMETHEUS_METRICS_PATH": env_value("PROMETHEUS_METRICS_PATH", combined_values, "/metrics") or "/metrics",
        "LOG_FORMAT": "json",
        "LOG_LEVEL": env_value("LOG_LEVEL", combined_values, "INFO") or "INFO",
        "LANGWATCH_ENABLED": monitoring_langwatch_enabled(),
        "LANGWATCH_ENDPOINT": normalize_langwatch_internal_endpoint(
            env_value("LANGWATCH_ENDPOINT", combined_values, "http://langwatch:5560")
        )
        or "http://langwatch:5560",
        "LANGWATCH_PUBLIC_URL": langwatch_public_url,
        "SUMMARIX_METRICS_TARGET": env_value("SUMMARIX_METRICS_TARGET", combined_values, "summarix-backend:8000") or "summarix-backend:8000",
        "LANGWATCH_APP_METRICS_TARGET": env_value(
            "LANGWATCH_APP_METRICS_TARGET",
            combined_values,
            "langwatch-app:5560",
        )
        or "langwatch-app:5560",
        "LANGWATCH_WORKERS_METRICS_TARGET": env_value(
            "LANGWATCH_WORKERS_METRICS_TARGET",
            combined_values,
            "langwatch-workers:2999",
        )
        or "langwatch-workers:2999",
        "METRICS_API_KEY": file_value("METRICS_API_KEY", combined_values, generate_secret()) or generate_secret(),
        "BASE_HOST": normalize_public_url_for_https(env_value("BASE_HOST", combined_values, langwatch_public_url)) or langwatch_public_url,
        "NEXTAUTH_URL": normalize_public_url_for_https(env_value("NEXTAUTH_URL", combined_values, langwatch_public_url)) or langwatch_public_url,
        "JWT_SECRET_KEY": file_value("JWT_SECRET_KEY", combined_values, generate_secret()) or generate_secret(),
        "NEXTAUTH_SECRET": file_value("NEXTAUTH_SECRET", combined_values, generate_secret()) or generate_secret(),
        "BETTER_AUTH_SECRET": file_value("BETTER_AUTH_SECRET", combined_values, generate_secret()) or generate_secret(),
        "CREDENTIALS_SECRET": file_value("CREDENTIALS_SECRET", combined_values, generate_secret()) or generate_secret(),
        "API_TOKEN_JWT_SECRET": file_value("API_TOKEN_JWT_SECRET", combined_values, generate_secret()) or generate_secret(),
        "LANGWATCH_TLS_CA_CERT_FILE": env_value("LANGWATCH_TLS_CA_CERT_FILE", combined_values, LANGWATCH_TLS_CA_CERT_DEFAULT) or LANGWATCH_TLS_CA_CERT_DEFAULT,
        "LANGWATCH_TLS_CERT_FILE": env_value("LANGWATCH_TLS_CERT_FILE", combined_values, LANGWATCH_TLS_CERT_DEFAULT) or LANGWATCH_TLS_CERT_DEFAULT,
        "LANGWATCH_TLS_KEY_FILE": env_value("LANGWATCH_TLS_KEY_FILE", combined_values, LANGWATCH_TLS_KEY_DEFAULT) or LANGWATCH_TLS_KEY_DEFAULT,
        "LANGWATCH_TLS_HOSTS": env_value("LANGWATCH_TLS_HOSTS", combined_values, "") or "",
        "LANGWATCH_DATABASE_URL": f"postgresql://{postgres_user}:{postgres_password}@postgres:5432/{postgres_db}?schema=langwatch",
        "LANGWATCH_CLICKHOUSE_URL": env_value(
            "LANGWATCH_CLICKHOUSE_URL",
            combined_values,
            "http://default:langwatch@clickhouse:8123/langwatch",
        )
        or "http://default:langwatch@clickhouse:8123/langwatch",
        "LANGWATCH_CLICKHOUSE_DATA_SOURCE": env_value(
            "LANGWATCH_CLICKHOUSE_DATA_SOURCE",
            combined_values,
            clickhouse_data_source,
        )
        or clickhouse_data_source,
        "LANGWATCH_REDIS_URL": env_value("LANGWATCH_REDIS_URL", combined_values, "redis://redis:6379") or "redis://redis:6379",
        "LANGWATCH_NLP_SERVICE": env_value("LANGWATCH_NLP_SERVICE", combined_values, "http://langwatch_nlp:5561") or "http://langwatch_nlp:5561",
        "LANGEVALS_ENDPOINT": env_value("LANGEVALS_ENDPOINT", combined_values, "http://langevals:5562") or "http://langevals:5562",
        "DASHSCOPE_API_BASE": env_value(
            "DASHSCOPE_API_BASE",
            combined_values,
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "CHAT_AGENT_MODE": env_value("CHAT_AGENT_MODE", combined_values, default_chat_mode) or default_chat_mode,
    }

    generated.update(api_key_values)
    return generated


def prepare_runtime_environment() -> tuple[dict[str, str], dict[str, str]]:
    ensure_runtime_layout()
    root_values = parse_env_file(ROOT_ENV)
    langwatch_values = parse_env_file(LANGWATCH_ENV)
    api_key_created = bootstrap_api_key_env(root_values, langwatch_values)
    api_key_values = parse_env_file(API_KEY_ENV)
    persisted_values = build_persisted_env(root_values, langwatch_values, parse_env_file(PERSISTED_ENV))
    previous_persisted = parse_env_file(PERSISTED_ENV)
    write_env_file(PERSISTED_ENV, persisted_values)
    generated_values = build_generated_env(root_values, langwatch_values, persisted_values, api_key_values)
    combined_values = dict(root_values)
    combined_values.update(langwatch_values)
    combined_values.update(persisted_values)
    combined_values.update(api_key_values)
    ensure_langwatch_tls_assets(generated_values)
    write_env_file(GENERATED_ENV, generated_values)

    if api_key_created:
        print("已自动创建 .env.api.key，请填写 DASHSCOPE_API_KEY 或其他模型 Key。")
    if previous_persisted != persisted_values:
        print("已生成并持久化自动密钥与本地密码，后续启动会复用 deploy/runtime/monitoring.persisted.env。")
    if not env_value("SUMMARIX_BACKEND_PORT", combined_values) and generated_values["SUMMARIX_BACKEND_PORT"] != DEFAULT_BACKEND_HOST_PORT:
        print(f"检测到默认端口 8000 已被占用，监控后端将改用宿主端口 {generated_values['SUMMARIX_BACKEND_PORT']}。")
    if not has_any_model_api_key(api_key_values):
        print("未检测到模型 API Key，本次将以 mock 模式启动后端；填写 .env.api.key 后会自动切回真实模型模式。")
    return {
        **root_values,
        **langwatch_values,
        **api_key_values,
    }, generated_values


def validate_backend_env(file_values: dict[str, str], *, local_db: bool) -> None:
    jwt_secret = env_value("JWT_SECRET_KEY", file_values)
    if not is_strong_secret(jwt_secret):
        raise CheckError("运行时 JWT_SECRET_KEY 缺失、仍是占位值，或长度不足 32。")
    if not local_db:
        database_url = env_value("DATABASE_URL", file_values)
        if not database_url:
            raise CheckError("缺少 DATABASE_URL；如果想使用 Docker 启动的共享数据库，请改用 make monitor-up。")
        database_host = host_from_url(database_url)
        if database_host in {None, "postgres"}:
            return


def validate_langwatch_env(file_values: dict[str, str]) -> None:
    required_keys = [
        "NEXTAUTH_SECRET",
        "BETTER_AUTH_SECRET",
        "CREDENTIALS_SECRET",
        "API_TOKEN_JWT_SECRET",
    ]
    missing = [key for key in required_keys if not env_value(key, file_values)]
    if missing:
        raise CheckError(f"运行时缺少 LangWatch 必填 secret: {', '.join(missing)}")
    weak = [
        key
        for key in required_keys
        if not is_strong_secret(env_value(key, file_values))
    ]
    if weak:
        raise CheckError(f"运行时这些 LangWatch secret 仍是占位值或过短: {', '.join(weak)}")


def fetch_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 5,
    insecure_tls: bool = False,
) -> tuple[int, str]:
    request = Request(url, headers=headers or {})
    ssl_context = ssl._create_unverified_context() if insecure_tls else None
    try:
        with urlopen(request, timeout=timeout, context=ssl_context) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return response.status, body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return exc.code, body
    except URLError as exc:
        raise CheckError(f"访问 {url} 失败: {exc.reason}") from exc
    except OSError as exc:
        raise CheckError(f"访问 {url} 失败: {exc}") from exc


def wait_http(
    url: str,
    *,
    expected_status: set[int],
    timeout_seconds: int,
    insecure_tls: bool = False,
) -> tuple[int, str]:
    deadline = time.time() + timeout_seconds
    last_error = "无响应"
    while time.time() < deadline:
        try:
            status, body = fetch_text(url, insecure_tls=insecure_tls)
            if status in expected_status:
                return status, body
            last_error = f"HTTP {status}: {body[:160]}"
        except CheckError as exc:
            last_error = str(exc)
        time.sleep(2)
    raise CheckError(f"等待 {url} 就绪超时，最后状态: {last_error}")


def basic_auth_headers(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def fetch_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 5) -> object:
    status, body = fetch_text(url, headers=headers, timeout=timeout)
    if status != 200:
        raise CheckError(f"访问 {url} 失败: HTTP {status}: {body[:160]}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise CheckError(f"访问 {url} 返回了无效 JSON。") from exc


def fetch_prometheus_targets(prometheus_port: str) -> list[dict[str, object]]:
    payload = fetch_json(f"http://127.0.0.1:{prometheus_port}/api/v1/targets")
    if not isinstance(payload, dict):
        raise CheckError("Prometheus targets API 返回了非对象响应。")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CheckError("Prometheus targets API 缺少 data 字段。")
    targets = data.get("activeTargets")
    if not isinstance(targets, list):
        raise CheckError("Prometheus targets API 缺少 activeTargets 数组。")
    return [item for item in targets if isinstance(item, dict)]


def wait_prometheus_targets(
    prometheus_port: str,
    *,
    required_jobs: dict[str, bool],
    timeout_seconds: int,
) -> list[dict[str, object]]:
    deadline = time.time() + timeout_seconds
    last_error = "尚未抓取到目标"
    while time.time() < deadline:
        targets = fetch_prometheus_targets(prometheus_port)
        target_health_by_job: dict[str, list[str]] = {}
        for item in targets:
            labels = item.get("labels")
            if not isinstance(labels, dict):
                continue
            job = labels.get("job", "unknown")
            health = str(item.get("health", "unknown"))
            target_health_by_job.setdefault(str(job), []).append(health)

        missing_jobs = [job for job, should_exist in required_jobs.items() if should_exist and job not in target_health_by_job]
        unhealthy_jobs = [
            job
            for job, should_exist in required_jobs.items()
            if should_exist and any(health != "up" for health in target_health_by_job.get(job, []))
        ]
        if not missing_jobs and not unhealthy_jobs:
            return targets
        last_error = (
            f"缺少目标: {', '.join(sorted(missing_jobs)) or '无'}；"
            f"未就绪目标: {', '.join(sorted(unhealthy_jobs)) or '无'}"
        )
        time.sleep(2)
    raise CheckError(f"Prometheus 抓取目标等待超时，最后状态: {last_error}")


def wait_grafana_dashboard(
    grafana_port: str,
    *,
    headers: dict[str, str],
    dashboard_uid: str,
    timeout_seconds: int,
) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_error = f"dashboard {dashboard_uid} 尚未出现"
    while time.time() < deadline:
        status, body = fetch_text(
            f"http://127.0.0.1:{grafana_port}/api/dashboards/uid/{dashboard_uid}",
            headers=headers,
            timeout=5,
        )
        if status == 200:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise CheckError("Grafana dashboard API 返回了无效 JSON。") from exc
            if isinstance(payload, dict):
                return payload
            raise CheckError("Grafana dashboard API 返回了非对象响应。")
        last_error = f"HTTP {status}: {body[:160]}"
        time.sleep(2)
    raise CheckError(f"等待 Grafana 仪表盘 {dashboard_uid} 就绪超时，最后状态: {last_error}")


def wait_grafana_dashboards(
    grafana_port: str,
    *,
    headers: dict[str, str],
    dashboard_uids: list[str],
    timeout_seconds: int,
) -> dict[str, dict[str, object]]:
    payloads: dict[str, dict[str, object]] = {}
    for dashboard_uid in dashboard_uids:
        payload = wait_grafana_dashboard(
            grafana_port,
            headers=headers,
            dashboard_uid=dashboard_uid,
            timeout_seconds=timeout_seconds,
        )
        payloads[dashboard_uid] = payload
    return payloads


def compose_service_running(compose_file: Path, service_name: str) -> bool:
    result = run_compose(compose_file, "ps", "-q", service_name, capture=True, check=False)
    return bool(result.stdout.strip())


def wait_postgres(timeout_seconds: int = 180) -> None:
    wait_shared_service_health("postgres", "共享 PostgreSQL", timeout_seconds=timeout_seconds)


def wait_redis(timeout_seconds: int = 180) -> None:
    wait_shared_service_health("redis", "共享 Redis", timeout_seconds=timeout_seconds)


def wait_shared_service_health(service_name: str, display_name: str, *, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_status = f"{service_name} 容器未创建"
    while time.time() < deadline:
        result = run_compose(SHARED_COMPOSE, "ps", "-q", service_name, capture=True, check=False)
        container_id = result.stdout.strip()
        if container_id:
            inspect = run_command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                    container_id,
                ],
                capture=True,
                check=False,
            )
            status = inspect.stdout.strip()
            if status == "healthy":
                print(f"{display_name} 已就绪。")
                return
            last_status = status or "unknown"
        time.sleep(2)
    raise CheckError(f"等待 {display_name} 就绪超时，最后状态: {last_status}")


def check_backend() -> None:
    file_values = effective_runtime_values()
    port = env_value("SUMMARIX_BACKEND_PORT", file_values, "8000") or "8000"
    wait_http(f"http://127.0.0.1:{port}/health", expected_status={200}, timeout_seconds=180)
    print(f"后端已就绪: http://127.0.0.1:{port}/health")


def check_plg() -> None:
    file_values = effective_runtime_values()
    prometheus_port = env_value("PROMETHEUS_PORT", file_values, "9090") or "9090"
    loki_port = env_value("LOKI_PORT", file_values, "3100") or "3100"
    grafana_port = env_value("GRAFANA_PORT", file_values, "3000") or "3000"
    grafana_user = env_value("GRAFANA_ADMIN_USER", file_values, "admin") or "admin"
    grafana_password = env_value("GRAFANA_ADMIN_PASSWORD", file_values, "please-change-me") or "please-change-me"

    wait_http(f"http://127.0.0.1:{prometheus_port}/-/ready", expected_status={200}, timeout_seconds=180)
    wait_http(f"http://127.0.0.1:{loki_port}/ready", expected_status={200}, timeout_seconds=180)
    wait_http(f"http://127.0.0.1:{grafana_port}/api/health", expected_status={200}, timeout_seconds=240)

    required_target_jobs = {
        "summarix-backend": compose_service_running(BACKEND_COMPOSE, "summarix-backend"),
        "langwatch-app": compose_service_running(LANGWATCH_COMPOSE, "app"),
        "langwatch-workers": compose_service_running(LANGWATCH_COMPOSE, "workers"),
    }
    targets = wait_prometheus_targets(
        prometheus_port,
        required_jobs=required_target_jobs,
        timeout_seconds=90,
    )
    target_summary: list[str] = []
    for item in targets:
        labels = item.get("labels")
        if not isinstance(labels, dict):
            continue
        job = str(labels.get("job", "unknown"))
        health = str(item.get("health", "unknown"))
        if job == "node-exporter" and platform.system() != "Linux" and health == "down":
            target_summary.append("node-exporter=skipped(当前平台默认跳过)")
            continue
        target_summary.append(f"{job}={health}")

    headers = basic_auth_headers(grafana_user, grafana_password)
    dashboard_uids = ["summarix-overview", "langwatch-overview"]
    datasources = fetch_json(f"http://127.0.0.1:{grafana_port}/api/datasources", headers=headers)
    if not isinstance(datasources, list):
        raise CheckError("Grafana 数据源 API 返回了非数组响应。")

    try:
        dashboard_payloads = wait_grafana_dashboards(
            grafana_port,
            headers=headers,
            dashboard_uids=dashboard_uids,
            timeout_seconds=20,
        )
    except CheckError:
        print("Grafana 仪表盘尚未注册，正在重启 Grafana 以重新加载 provisioning...")
        run_compose(PLG_COMPOSE, "restart", "grafana")
        wait_http(f"http://127.0.0.1:{grafana_port}/api/health", expected_status={200}, timeout_seconds=240)
        datasources = fetch_json(f"http://127.0.0.1:{grafana_port}/api/datasources", headers=headers)
        if not isinstance(datasources, list):
            raise CheckError("Grafana 数据源 API 返回了非数组响应。")
        dashboard_payloads = wait_grafana_dashboards(
            grafana_port,
            headers=headers,
            dashboard_uids=dashboard_uids,
            timeout_seconds=30,
        )

    rules_payload = fetch_json(f"http://127.0.0.1:{prometheus_port}/api/v1/rules")
    if not isinstance(rules_payload, dict):
        raise CheckError("Prometheus rules API 返回了非对象响应。")
    data = rules_payload.get("data")
    if not isinstance(data, dict):
        raise CheckError("Prometheus rules API 缺少 data 字段。")
    groups = data.get("groups")
    if not isinstance(groups, list):
        raise CheckError("Prometheus rules API 缺少 groups 数组。")
    rule_group_names = sorted(
        str(group.get("name"))
        for group in groups
        if isinstance(group, dict) and group.get("name")
    )
    if "langwatch-self-hosted" not in rule_group_names:
        raise CheckError("Prometheus 尚未加载 langwatch-self-hosted 告警规则组。")

    datasource_names = ", ".join(sorted(item["name"] for item in datasources))
    dashboard_summaries: list[str] = []
    for dashboard_uid, dashboard_payload in dashboard_payloads.items():
        dashboard_title = dashboard_uid
        if isinstance(dashboard_payload, dict):
            dashboard = dashboard_payload.get("dashboard")
            if isinstance(dashboard, dict):
                dashboard_title = str(dashboard.get("title") or dashboard_uid)
        dashboard_summaries.append(f"{dashboard_title} ({dashboard_uid})")

    print(f"Prometheus 已就绪: http://127.0.0.1:{prometheus_port}")
    print(f"Loki 已就绪: http://127.0.0.1:{loki_port}")
    print(f"Grafana 已就绪: http://127.0.0.1:{grafana_port}")
    print(f"Prometheus 目标状态: {', '.join(target_summary)}")
    print(f"Prometheus 规则组: {', '.join(rule_group_names)}")
    print(f"Grafana 数据源: {datasource_names}")
    print(f"Grafana 仪表盘: {', '.join(dashboard_summaries)}")
    metrics_target = env_value("SUMMARIX_METRICS_TARGET", file_values, "summarix-backend:8000") or "summarix-backend:8000"
    langwatch_app_target = env_value("LANGWATCH_APP_METRICS_TARGET", file_values, "langwatch-app:5560") or "langwatch-app:5560"
    langwatch_workers_target = env_value("LANGWATCH_WORKERS_METRICS_TARGET", file_values, "langwatch-workers:2999") or "langwatch-workers:2999"
    print(f"当前 Prometheus 抓取目标: {metrics_target}, {langwatch_app_target}, {langwatch_workers_target}")
    if platform.system() != "Linux":
        print("当前平台非 Linux，node-exporter 默认不会启动；这是为兼容 Docker Desktop。")


def check_langwatch() -> None:
    file_values = effective_runtime_values()
    port = env_value("LANGWATCH_PORT", file_values, "5560") or "5560"
    public_url = normalize_public_url_for_https(env_value("LANGWATCH_PUBLIC_URL", file_values, f"https://127.0.0.1:{port}")) or f"https://127.0.0.1:{port}"
    wait_http(f"https://127.0.0.1:{port}/", expected_status={200}, timeout_seconds=600, insecure_tls=True)
    print(f"LangWatch 已就绪: {public_url}")


def shared_up() -> None:
    try:
        run_compose(SHARED_COMPOSE, "up", "-d", "--remove-orphans")
        wait_postgres()
        wait_redis()
    except CheckError:
        show_logs(SHARED_COMPOSE)
        raise


def shared_down() -> None:
    run_compose(SHARED_COMPOSE, "down", "--remove-orphans", check=False)
    print("共享 PostgreSQL 已停止。")


def backend_up(*, local_db: bool) -> None:
    ensure_docker_ready()
    manual_values, generated_values = prepare_runtime_environment()
    validate_backend_env(generated_values if local_db else manual_values, local_db=local_db)
    if local_db:
        shared_up()
    try:
        start_backend_stack(generated_values)
        check_backend()
    except CheckError:
        show_logs([SHARED_COMPOSE, BACKEND_COMPOSE] if local_db else BACKEND_COMPOSE)
        raise


def backend_down(*, local_db: bool) -> None:
    ensure_docker_ready()
    run_compose(BACKEND_COMPOSE, "down", "--remove-orphans", check=False)
    if local_db:
        shared_down()
    print("监控用后端 compose 已停止。")


def host_metrics_profiles(file_values: dict[str, str] | None = None) -> list[str]:
    if platform.system() != "Linux":
        return []
    runtime_values = file_values or effective_runtime_values()
    return ["host-metrics"] if env_flag_enabled("PLG_HOST_METRICS_ENABLED", runtime_values, "true") else []


def start_plg_stack(file_values: dict[str, str] | None = None) -> None:
    profiles = host_metrics_profiles(file_values)
    if not profiles:
        run_compose(PLG_COMPOSE, "up", "-d", "--remove-orphans")
        return
    try:
        run_compose(PLG_COMPOSE, "up", "-d", "--remove-orphans", profiles=profiles)
    except CheckError as exc:
        print(f"启用 host-metrics 失败，正在退回核心 PLG 栈重试: {exc}")
        run_compose(PLG_COMPOSE, "down", "--remove-orphans", profiles=profiles, check=False)
        run_compose(PLG_COMPOSE, "up", "-d", "--remove-orphans")


def plg_up() -> None:
    ensure_docker_ready()
    prepare_runtime_environment()
    try:
        start_plg_stack()
        check_plg()
    except CheckError:
        show_logs(PLG_COMPOSE)
        raise


def plg_down() -> None:
    ensure_docker_ready()
    run_compose(PLG_COMPOSE, "down", "--remove-orphans", check=False)
    print("PLG 监控栈已停止。")


def langwatch_up() -> None:
    ensure_docker_ready()
    _, generated_values = prepare_runtime_environment()
    validate_langwatch_env(generated_values)
    shared_up()
    try:
        run_compose(LANGWATCH_COMPOSE, "up", "-d", "--remove-orphans")
        run_compose(LANGWATCH_COMPOSE, "restart", "tls_proxy")
        check_langwatch()
        ensure_langwatch_api_key_configured()
        prepare_runtime_environment()
    except CheckError:
        show_logs([SHARED_COMPOSE, LANGWATCH_COMPOSE])
        raise


def langwatch_down() -> None:
    ensure_docker_ready()
    run_compose(LANGWATCH_COMPOSE, "down", "--remove-orphans", check=False)
    print("LangWatch 栈已停止。")


def all_up() -> None:
    ensure_docker_ready()
    _, generated_values = prepare_runtime_environment()
    validate_backend_env(generated_values, local_db=True)
    validate_langwatch_env(generated_values)
    try:
        shared_up()
        run_compose(LANGWATCH_COMPOSE, "up", "-d", "--remove-orphans")
        run_compose(LANGWATCH_COMPOSE, "restart", "tls_proxy")
        check_langwatch()
        ensure_langwatch_api_key_configured()
        _, generated_values = prepare_runtime_environment()
        validate_backend_env(generated_values, local_db=True)
        start_backend_stack(generated_values)
        start_plg_stack(generated_values)
        check_backend()
        check_plg()
    except CheckError:
        show_logs([SHARED_COMPOSE, BACKEND_COMPOSE, PLG_COMPOSE, LANGWATCH_COMPOSE])
        raise


def all_down() -> None:
    ensure_docker_ready()
    run_compose(LANGWATCH_COMPOSE, "down", "--remove-orphans", check=False)
    run_compose(PLG_COMPOSE, "down", "--remove-orphans", check=False)
    run_compose(BACKEND_COMPOSE, "down", "--remove-orphans", check=False)
    run_compose(SHARED_COMPOSE, "down", "--remove-orphans", check=False)
    print("一键监控栈已停止。")


def all_check() -> None:
    ensure_docker_ready()
    wait_postgres(timeout_seconds=60)
    wait_redis(timeout_seconds=60)
    check_backend()
    check_plg()
    check_langwatch()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarix 监控栈启停与就绪检查工具")
    parser.add_argument("stack", choices=["backend", "plg", "langwatch", "all"])
    parser.add_argument("action", choices=["up", "down", "check"])
    parser.add_argument("--local-db", action="store_true", help="backend up/down 使用，同时管理 deploy/shared 下的 PostgreSQL。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.stack == "backend":
            if args.action == "up":
                backend_up(local_db=args.local_db)
            elif args.action == "down":
                backend_down(local_db=args.local_db)
            else:
                ensure_docker_ready()
                check_backend()
        elif args.stack == "plg":
            if args.action == "up":
                plg_up()
            elif args.action == "down":
                plg_down()
            else:
                ensure_docker_ready()
                check_plg()
        elif args.stack == "langwatch":
            if args.action == "up":
                langwatch_up()
            elif args.action == "down":
                langwatch_down()
            else:
                ensure_docker_ready()
                check_langwatch()
        else:
            if args.action == "up":
                all_up()
            elif args.action == "down":
                all_down()
            else:
                all_check()
    except CheckError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())