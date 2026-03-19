from __future__ import annotations

import base64
import html
import mimetypes
import re
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # type: ignore[import-not-found]
    from playwright.sync_api import sync_playwright as playwright_sync_playwright  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - handled by runtime check
    PlaywrightTimeoutError = RuntimeError
    playwright_sync_playwright = None


MAX_PNG_HEIGHT = 16000


class ExportRenderError(RuntimeError):
    """Raised when an export artifact cannot be rendered safely."""


def render_pdf(
    html_document: str,
    *,
    avatar_source_url: str | None = None,
    avatar_data_url: str | None = None,
    timeout_ms: int = 45_000,
) -> bytes:
    resolved_avatar_data_url = avatar_data_url or build_avatar_data_url(avatar_source_url)
    prepared = _prepare_export_html(
        html_document,
        avatar_source_url=avatar_source_url,
        avatar_data_url=resolved_avatar_data_url,
    )
    return _with_page(
        prepared,
        timeout_ms=timeout_ms,
        callback=lambda page: page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "14mm", "right": "12mm", "bottom": "14mm", "left": "12mm"},
        ),
    )


def render_png(
    html_document: str,
    *,
    avatar_source_url: str | None = None,
    avatar_data_url: str | None = None,
    timeout_ms: int = 45_000,
    max_height: int = MAX_PNG_HEIGHT,
) -> bytes:
    resolved_avatar_data_url = avatar_data_url or build_avatar_data_url(avatar_source_url)
    prepared = _prepare_export_html(
        html_document,
        avatar_source_url=avatar_source_url,
        avatar_data_url=resolved_avatar_data_url,
    )

    def capture(page: Any) -> bytes:
        height = page.evaluate("() => Math.ceil(document.documentElement.scrollHeight)")
        if int(height) > max_height:
            raise ExportRenderError(
                f"Report is too tall for PNG export ({height}px). Please use PDF instead."
            )
        return page.screenshot(full_page=True, type="png")

    return _with_page(prepared, timeout_ms=timeout_ms, callback=capture)


def freeze_standalone_html(
    html_document: str,
    *,
    avatar_source_url: str | None = None,
    avatar_data_url: str | None = None,
    timeout_ms: int = 45_000,
) -> str:
    resolved_avatar_data_url = avatar_data_url or build_avatar_data_url(avatar_source_url)
    document = _prepare_export_html(
        html_document,
        avatar_source_url=avatar_source_url,
        avatar_data_url=resolved_avatar_data_url,
    )

    def freeze(page: Any) -> str:
        page.evaluate(_FREEZE_EXPORT_SCRIPT)
        return page.content()

    return _with_page(document, timeout_ms=timeout_ms, callback=freeze)


def build_avatar_data_url(source_url: str | None, *, timeout_seconds: float = 15.0) -> str | None:
    if not source_url or not _is_http_url(source_url) or not _is_allowed_avatar_host(source_url):
        return None
    response = httpx.get(source_url, timeout=timeout_seconds)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()
    if not content_type or content_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(source_url)
        content_type = guessed or "application/octet-stream"
    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def ensure_playwright_available() -> None:
    if playwright_sync_playwright is None:
        raise ExportRenderError(
            "Playwright is not installed. Install the 'playwright' package and browser runtime first."
        )


def _with_page(html_document: str, *, timeout_ms: int, callback: Any) -> Any:
    ensure_playwright_available()
    playwright_factory = _playwright_factory()
    try:
        with playwright_factory() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
            page.set_content(html_document, wait_until="load", timeout=timeout_ms)
            page.emulate_media(media="screen")
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            page.wait_for_timeout(750)
            result = callback(page)
            browser.close()
            return result
    except PlaywrightTimeoutError as error:
        raise ExportRenderError("Timed out while rendering export artifact.") from error


def _replace_chart_cdn(html_document: str) -> str:
    script = "<script>window.ChartRenderMode='export';</script>"
    return html_document.replace(
        '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
        script,
    )


def _replace_avatar_urls(html_document: str, avatar_source_url: str, avatar_data_url: str) -> str:
    return html_document.replace(
        html.escape(avatar_source_url, quote=True),
        html.escape(avatar_data_url, quote=True),
    )


def _strip_remote_font_imports(html_document: str) -> str:
    document = re.sub(
        r"<link rel=\"preconnect\" href=\"https://fonts\.googleapis\.com\" ?/>",
        "",
        html_document,
    )
    document = re.sub(
        r"<link rel=\"preconnect\" href=\"https://fonts\.gstatic\.com\" crossorigin ?/>",
        "",
        document,
    )
    document = _GOOGLE_FONT_STYLESHEET_RE.sub("", document)
    document = re.sub(r"@import url\('https://fonts\.googleapis\.com[^']+'\);", "", document)
    return document


def _is_http_url(value: str) -> bool:
    scheme = urlsplit(value).scheme.lower()
    return scheme in {"http", "https"}


def _is_allowed_avatar_host(value: str) -> bool:
    host = (urlsplit(value).hostname or "").lower()
    return host in {"avatars.githubusercontent.com", "github.com"}


def _prepare_export_html(
    html_document: str,
    *,
    avatar_source_url: str | None = None,
    avatar_data_url: str | None = None,
) -> str:
    document = _strip_remote_font_imports(html_document)
    document = _replace_chart_cdn(document)
    if avatar_source_url and avatar_data_url:
        document = _replace_avatar_urls(document, avatar_source_url, avatar_data_url)
    elif avatar_source_url:
        document = document.replace(html.escape(avatar_source_url, quote=True), "")
    return document


def _playwright_factory() -> Callable[..., Any]:
    if playwright_sync_playwright is None:
        raise ExportRenderError(
            "Playwright is not installed. Install the 'playwright' package and browser runtime first."
        )
    return playwright_sync_playwright


_GOOGLE_FONT_STYLESHEET_RE = re.compile(
    r'<link href="https://fonts\.googleapis\.com[^"]+" rel="stylesheet" ?/>'
)


_FREEZE_EXPORT_SCRIPT = r"""
() => {
  const renderFallbackCharts = () => {
    const payload = window.payload || {};
    const specs = [
      { id: 'commitsChart', type: 'line', data: payload.commits || null },
      { id: 'locChart', type: 'bar', data: payload.loc || null },
      { id: 'languageChart', type: 'pie', data: payload.languages || null },
    ];

    const drawLine = (ctx, width, height, chartData) => {
      const labels = chartData.labels || [];
      const series = (chartData.series || [])[0] || null;
      const values = series ? series.values || [] : [];
      const max = Math.max(...values, 1);
      ctx.strokeStyle = series?.color || '#0f766e';
      ctx.lineWidth = 3;
      ctx.beginPath();
      values.forEach((value, index) => {
        const x = 28 + ((width - 56) * index) / Math.max(values.length - 1, 1);
        const y = height - 24 - ((height - 48) * value) / max;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = 'rgba(127,127,127,0.18)';
      ctx.font = '12px sans-serif';
      if (labels.length) {
        ctx.fillText(labels[0], 16, height - 6);
        ctx.fillText(labels[labels.length - 1], Math.max(16, width - 120), height - 6);
      }
    };

    const drawBar = (ctx, width, height, chartData) => {
      const series = chartData.series || [];
      const first = series[0]?.values || [];
      const second = series[1]?.values || [];
      const max = Math.max(...first, ...second, 1);
      const count = Math.max(first.length, second.length, 1);
      const slot = (width - 40) / count;
      for (let index = 0; index < count; index += 1) {
        const x = 20 + slot * index;
        const barWidth = Math.max(slot / 3, 6);
        const firstHeight = ((height - 36) * (first[index] || 0)) / max;
        const secondHeight = ((height - 36) * (second[index] || 0)) / max;
        ctx.fillStyle = series[0]?.color || '#16a34a';
        ctx.fillRect(x, height - 20 - firstHeight, barWidth, firstHeight);
        ctx.fillStyle = series[1]?.color || '#dc2626';
        ctx.fillRect(x + barWidth + 3, height - 20 - secondHeight, barWidth, secondHeight);
      }
    };

    const drawPie = (ctx, width, height, chartData) => {
      const values = chartData.values || [];
      const colors = chartData.colors || [];
      const total = values.reduce((sum, value) => sum + value, 0) || 1;
      let angle = -Math.PI / 2;
      const radius = Math.min(width, height) / 2 - 18;
      values.forEach((value, index) => {
        const slice = (value / total) * Math.PI * 2;
        ctx.beginPath();
        ctx.moveTo(width / 2, height / 2);
        ctx.arc(width / 2, height / 2, radius, angle, angle + slice);
        ctx.closePath();
        ctx.fillStyle = colors[index] || '#999';
        ctx.fill();
        angle += slice;
      });
    };

    specs.forEach((spec) => {
      const canvas = document.getElementById(spec.id);
      if (!canvas || !spec.data) return;
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(Math.ceil(rect.width || 640), 320);
      const height = Math.max(Math.ceil(rect.height || 280), 220);
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, width, height);
      if (spec.type === 'line') drawLine(ctx, width, height, spec.data);
      if (spec.type === 'bar') drawBar(ctx, width, height, spec.data);
      if (spec.type === 'pie') drawPie(ctx, width, height, spec.data);
    });
  };

  if (typeof window.Chart === 'undefined') {
    renderFallbackCharts();
  }

  document.querySelectorAll('canvas').forEach((canvas) => {
    try {
      const dataUrl = canvas.toDataURL('image/png');
      const img = document.createElement('img');
      img.src = dataUrl;
      img.alt = canvas.id || 'chart';
      img.style.width = canvas.style.width || `${canvas.getBoundingClientRect().width || canvas.width}px`;
      img.style.height = canvas.style.height || `${canvas.getBoundingClientRect().height || canvas.height}px`;
      img.style.display = 'block';
      img.style.maxWidth = '100%';
      canvas.replaceWith(img);
    } catch (error) {
      console.warn('failed to freeze canvas', error);
    }
  });
}
"""
