"""Безопасная загрузка сайтов, очистка HTML и пошаговый анализ через LLM."""

import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from app.services.llm_client import LLMClient


CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 15.0
TOTAL_FETCH_TIMEOUT_SECONDS = 30.0
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 64 * 1024

INVALID_URL_MESSAGE = "URL сайта недопустим или заблокирован"
FETCH_FAILED_MESSAGE = "Не удалось безопасно загрузить сайт"
FETCH_TIMEOUT_MESSAGE = "Превышено допустимое время загрузки сайта"
RESPONSE_TOO_LARGE_MESSAGE = "Сайт слишком большой для анализа"
UNSUPPORTED_CONTENT_TYPE_MESSAGE = "Тип содержимого сайта не поддерживается"
UNSUPPORTED_CONTENT_ENCODING_MESSAGE = "Кодирование содержимого сайта не поддерживается"

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_PORTS = frozenset({80, 443})
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_LOCAL_HOSTNAME_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".lan",
    ".home.arpa",
    ".test",
    ".invalid",
)
_HOST_LABEL_RE = re.compile(r"^[a-z0-9-]+$")
_HOST_PORT_RE = re.compile(r"^[^/?#]+:\d+(?:[/?#]|$)")
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9",
    "Accept-Encoding": "identity",
}


class AnalyzerError(Exception):
    """Ошибка анализа или обработки содержимого сайта."""

    pass


class SiteFetchError(AnalyzerError):
    """Контролируемая ошибка загрузки с безопасным сообщением для API."""

    def __init__(self, public_message: str, status_code: int) -> None:
        super().__init__(public_message)
        self.public_message = public_message
        self.status_code = status_code


def _invalid_url_error() -> SiteFetchError:
    return SiteFetchError(INVALID_URL_MESSAGE, status_code=400)


def normalize_url(url: str) -> str:
    """Добавляет https:// при отсутствии схемы и отбрасывает пустой ввод."""
    normalized = (url or "").strip()
    if not normalized:
        raise _invalid_url_error()
    if any(character.isspace() or ord(character) < 32 for character in normalized):
        raise _invalid_url_error()

    try:
        parsed = urlsplit(normalized)
    except ValueError as exc:
        raise _invalid_url_error() from exc

    if not parsed.scheme or _HOST_PORT_RE.match(normalized):
        normalized = "https://" + normalized
    return normalized


def _normalize_hostname(
    hostname: str,
) -> tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address | None]:
    hostname = hostname.rstrip(".").lower()
    if not hostname or "%" in hostname:
        raise _invalid_url_error()

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None

    if address is not None:
        return address.compressed, address

    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise _invalid_url_error() from exc

    labels = ascii_hostname.split(".")
    if (
        len(ascii_hostname) > 253
        or len(labels) < 2
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not _HOST_LABEL_RE.fullmatch(label)
            for label in labels
        )
    ):
        raise _invalid_url_error()

    if any(
        ascii_hostname == suffix.removeprefix(".") or ascii_hostname.endswith(suffix)
        for suffix in _LOCAL_HOSTNAME_SUFFIXES
    ):
        raise _invalid_url_error()

    return ascii_hostname, None


def _address_is_unsafe(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        if _address_is_unsafe(address.ipv4_mapped):
            return True
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or getattr(address, "is_site_local", False)
        or not address.is_global
    )


# TOTAL_FETCH_TIMEOUT_SECONDS is an application budget, not a hard OS deadline:
# synchronous socket.getaddrinfo follows OS resolver timeouts. Validation and the
# HTTP connection resolve separately, so DNS rebinding remains a residual risk;
# deployment egress restrictions are the intended defense-in-depth control.
def _resolve_host_addresses(
    hostname: str,
    port: int,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    try:
        records = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise SiteFetchError(FETCH_FAILED_MESSAGE, status_code=502) from exc

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for family, _socket_type, _protocol, _canonical_name, socket_address in records:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            addresses.add(ipaddress.ip_address(socket_address[0]))
        except ValueError:
            continue

    if not addresses:
        raise SiteFetchError(FETCH_FAILED_MESSAGE, status_code=502)
    return tuple(sorted(addresses, key=str))


def validate_and_resolve_url(url: str) -> str:
    """Проверяет URL и отклоняет адрес, если хотя бы один DNS-ответ небезопасен."""
    normalized = normalize_url(url)
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise _invalid_url_error() from exc

    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise _invalid_url_error()
    if not parsed.netloc or chr(92) in parsed.netloc:
        raise _invalid_url_error()
    if parsed.username is not None or parsed.password is not None:
        raise _invalid_url_error()
    if parsed.netloc.endswith(":") and port is None:
        raise _invalid_url_error()
    if port is not None and port not in _ALLOWED_PORTS:
        raise _invalid_url_error()

    hostname = parsed.hostname
    if hostname is None:
        raise _invalid_url_error()
    ascii_hostname, literal_address = _normalize_hostname(hostname)

    effective_port = port or (443 if scheme == "https" else 80)
    addresses = (
        (literal_address,)
        if literal_address is not None
        else _resolve_host_addresses(ascii_hostname, effective_port)
    )
    if any(_address_is_unsafe(address) for address in addresses):
        raise _invalid_url_error()

    netloc_hostname = f"[{ascii_hostname}]" if ":" in ascii_hostname else ascii_hostname
    netloc = f"{netloc_hostname}:{port}" if port is not None else netloc_hostname
    return urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))


def _validated_content_type(response: requests.Response) -> None:
    content_type = response.headers.get("Content-Type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in _HTML_CONTENT_TYPES:
        raise SiteFetchError(UNSUPPORTED_CONTENT_TYPE_MESSAGE, status_code=415)


def _validated_content_encoding(response: requests.Response) -> None:
    content_encoding = response.headers.get("Content-Encoding")
    if content_encoding is not None and content_encoding.strip().lower() != "identity":
        raise SiteFetchError(UNSUPPORTED_CONTENT_ENCODING_MESSAGE, status_code=415)


def _reject_oversized_content_length(
    response: requests.Response,
    maximum_bytes: int,
) -> None:
    value = response.headers.get("Content-Length")
    if value is None:
        return
    try:
        content_length = int(value)
    except (TypeError, ValueError):
        return
    if content_length > maximum_bytes:
        raise SiteFetchError(RESPONSE_TOO_LARGE_MESSAGE, status_code=413)


def _read_bounded_body(
    response: requests.Response,
    maximum_bytes: int,
    deadline: float,
) -> bytes:
    chunks: list[bytes] = []
    downloaded = 0
    try:
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            if time.monotonic() > deadline:
                raise SiteFetchError(FETCH_TIMEOUT_MESSAGE, status_code=504)
            if not chunk:
                continue
            downloaded += len(chunk)
            if downloaded > maximum_bytes:
                raise SiteFetchError(RESPONSE_TOO_LARGE_MESSAGE, status_code=413)
            chunks.append(chunk)
    except requests.RequestException as exc:
        raise SiteFetchError(FETCH_FAILED_MESSAGE, status_code=502) from exc
    return b"".join(chunks)


def _decode_html(body: bytes, response: requests.Response) -> str:
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch_html(
    url: str,
    connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
    read_timeout: float = READ_TIMEOUT_SECONDS,
    maximum_bytes: int = MAX_RESPONSE_BYTES,
    maximum_redirects: int = MAX_REDIRECTS,
    total_timeout: float = TOTAL_FETCH_TIMEOUT_SECONDS,
) -> str:
    """Безопасно загружает ограниченный HTML с ручной проверкой редиректов."""
    deadline = time.monotonic() + total_timeout
    current_url = validate_and_resolve_url(url)
    visited_urls = {current_url}
    redirect_count = 0
    session = requests.Session()
    session.trust_env = False

    try:
        while True:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise SiteFetchError(FETCH_TIMEOUT_MESSAGE, status_code=504)

            try:
                response = session.get(
                    current_url,
                    timeout=(
                        min(connect_timeout, remaining_time),
                        min(read_timeout, remaining_time),
                    ),
                    allow_redirects=False,
                    stream=True,
                    headers=_FETCH_HEADERS,
                )
            except (requests.RequestException, OSError) as exc:
                raise SiteFetchError(FETCH_FAILED_MESSAGE, status_code=502) from exc

            try:
                _validated_content_encoding(response)
                try:
                    response.raise_for_status()
                except requests.RequestException as exc:
                    raise SiteFetchError(FETCH_FAILED_MESSAGE, status_code=502) from exc

                if response.status_code in _REDIRECT_STATUS_CODES:
                    if redirect_count >= maximum_redirects:
                        raise SiteFetchError(FETCH_FAILED_MESSAGE, status_code=502)
                    location = response.headers.get("Location")
                    if not location:
                        raise SiteFetchError(FETCH_FAILED_MESSAGE, status_code=502)

                    redirect_url = validate_and_resolve_url(urljoin(current_url, location))
                    if redirect_url in visited_urls:
                        raise SiteFetchError(FETCH_FAILED_MESSAGE, status_code=502)
                    visited_urls.add(redirect_url)
                    current_url = redirect_url
                    redirect_count += 1
                    continue

                _validated_content_type(response)
                _reject_oversized_content_length(response, maximum_bytes)
                body = _read_bounded_body(response, maximum_bytes, deadline)
                return _decode_html(body, response)
            finally:
                response.close()
    finally:
        session.close()


def clean_html_to_text(html: str) -> str:
    """
    Удаляет HTML-теги и возвращает только текст.

    Args:
        html: Исходный HTML.

    Returns:
        Очищенный текст (без тегов).

    Raises:
        AnalyzerError: при ошибке парсинга.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        if not text or not text.strip():
            raise AnalyzerError("После очистки HTML текст пуст")
        return text
    except AnalyzerError:
        raise
    except Exception as e:
        raise AnalyzerError("Не удалось обработать содержимое сайта") from e


def _extract_steps_list(data: dict) -> list[str]:
    """Извлекает список шагов из ответа LLM (поддержка полей steps / prompts)."""
    for key in ("steps", "prompts", "шаги", "промпты"):
        if key in data and isinstance(data[key], list):
            return [str(s) for s in data[key]]
    if isinstance(data, list):
        return [str(s) for s in data]
    raise ValueError("В ответе LLM не найден список шагов (ожидаются ключи steps или prompts)")


def run_site_analysis(url: str, llm_client: LLMClient) -> dict:
    """
    Выполняет полный анализ сайта по URL: загрузка, очистка, шаги LLM, финальный отчёт.

    Args:
        url: URL сайта для анализа.
        llm_client: Клиент LLM для запросов.

    Returns:
        Словарь с ключами: url, steps, intermediate_results, final_analysis.
        final_analysis может быть dict (если LLM вернул JSON) или строка.

    Raises:
        AnalyzerError: при ошибке загрузки или парсинга HTML (для HTTP 400).
    """
    url = normalize_url(url)
    html = fetch_html(url)
    cleaned_text = clean_html_to_text(html)

    # 1) Первый запрос: получить список шагов в JSON
    steps_prompt = (
        "Ты бот-анализатор сайтов. Вот текст сайта: [очищенный текст]. "
        "В ответе в формате JSON выдай список из 5-6 шагов (промптов), которые нужно выполнить "
        "для анализа этого сайта и подготовки краткого резюме содержания этого сайта (3-5 предложений)."
    )
    user_with_text = f"Текст сайта:\n\n{cleaned_text[:50000]}"  # ограничение длины
    steps_schema = '{"steps": ["промпт шага 1", "промпт шага 2", ...]}'

    steps_response = llm_client.chat_json(
        system_prompt=steps_prompt,
        user_prompt=user_with_text,
        json_schema=steps_schema,
    )
    steps: list[str] = _extract_steps_list(steps_response)

    # 2) Для каждого шага: системный промпт = шаг, user_prompt = очищенный текст
    intermediate_results: list[str] = []
    for step in steps:
        reply = llm_client.chat_with_system(
            system_prompt=step,
            user_prompt=cleaned_text[:50000],
        )
        intermediate_results.append(reply)

    # 3) Финальный запрос: объединить промежуточные результаты и получить итог
    final_system = (
        "У тебя есть результаты промежуточного анализа: [список ответов]. "
        "Объедини их и выдай итоговый анализ сайта. Ответ должен содержать: краткий анализ, "
        "инструкцию по созданию краткого содержания сайта и три примера вывода такого краткого содержания сайта. "
        "Обязательно включи в анализ оригинальный текст сайта. Ответь в формате JSON."
    )
    intermediate_blob = "\n\n---\n\n".join(
        f"Результат шага {i+1}:\n{r}" for i, r in enumerate(intermediate_results)
    )
    final_user = f"Промежуточные результаты:\n\n{intermediate_blob}\n\nОригинальный текст сайта (фрагмент):\n\n{cleaned_text[:15000]}"
    final_schema = (
        '{"analysis": "краткий анализ сайта", "summary_instruction": "инструкция по созданию краткого содержания", '
        '"example_summaries": ["пример 1", "пример 2", "пример 3"]}'
    )

    final_response = llm_client.chat_json(
        system_prompt=final_system,
        user_prompt=final_user,
        json_schema=final_schema,
    )

    return {
        "url": url,
        "steps": steps,
        "intermediate_results": intermediate_results,
        "final_analysis": final_response,
    }
