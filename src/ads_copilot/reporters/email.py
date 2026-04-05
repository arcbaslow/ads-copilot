"""Email delivery via SMTP. Multipart (HTML + plain text fallback)."""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ads_copilot.reporters.formatters import AuditReport, format_markdown

log = logging.getLogger(__name__)


class EmailError(RuntimeError):
    pass


@dataclass(slots=True)
class EmailReporter:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    from_addr: str
    to: list[str]
    use_tls: bool = True
    timeout: float = 30.0

    @classmethod
    def from_config(
        cls,
        smtp_host: str,
        smtp_port: int,
        smtp_user_env: str,
        smtp_password_env: str,
        from_addr: str,
        to: list[str],
    ) -> EmailReporter:
        user = os.environ.get(smtp_user_env)
        password = os.environ.get(smtp_password_env)
        if not user or not password:
            raise EmailError(
                f"env vars {smtp_user_env} and {smtp_password_env} must be set"
            )
        if not to:
            raise EmailError("no recipients configured for email delivery")
        return cls(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=user,
            smtp_password=password,
            from_addr=from_addr or user,
            to=to,
        )

    async def send(self, report: AuditReport) -> None:
        """Send the audit report. smtplib is blocking so we thread it out."""
        subject = (
            f"Ads Report — {report.report_date.strftime('%Y-%m-%d')} "
            f"({report.period_label})"
        )
        md = format_markdown(report)
        html = _markdown_to_html(md)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to)
        msg.attach(MIMEText(md, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        await asyncio.to_thread(self._send_sync, msg)

    def _send_sync(self, msg: MIMEMultipart) -> None:
        context = ssl.create_default_context()
        try:
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(
                    self.smtp_host, self.smtp_port,
                    timeout=self.timeout, context=context,
                ) as server:
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(
                    self.smtp_host, self.smtp_port, timeout=self.timeout,
                ) as server:
                    if self.use_tls:
                        server.starttls(context=context)
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            raise EmailError(f"SMTP delivery failed: {e}") from e


def _markdown_to_html(md: str) -> str:
    """Very small markdown-to-HTML shim. Avoids a markdown dep.

    Handles: h1/h2 headers, pipe tables, bold, inline code, line breaks.
    Good enough for the audit-report format we generate.
    """
    lines = md.split("\n")
    out: list[str] = ["<html><body style='font-family: -apple-system, Segoe UI, sans-serif;'>"]
    in_table = False
    for raw in lines:
        line = raw.rstrip()
        if line.startswith("# "):
            _close_table(out, in_table)
            in_table = False
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            _close_table(out, in_table)
            in_table = False
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("|") and line.endswith("|"):
            if not in_table:
                out.append('<table border="1" cellpadding="4" cellspacing="0">')
                in_table = True
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # separator row
            row = "".join(f"<td>{_inline(c)}</td>" for c in cells)
            out.append(f"<tr>{row}</tr>")
        elif line.startswith("- "):
            _close_table(out, in_table)
            in_table = False
            out.append(f"<p>• {_inline(line[2:])}</p>")
        elif line.strip() == "":
            _close_table(out, in_table)
            in_table = False
            out.append("")
        else:
            _close_table(out, in_table)
            in_table = False
            out.append(f"<p>{_inline(line)}</p>")
    _close_table(out, in_table)
    out.append("</body></html>")
    return "\n".join(out)


def _close_table(out: list[str], in_table: bool) -> None:
    if in_table:
        out.append("</table>")


def _inline(text: str) -> str:
    # Escape, then apply bold and code
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Bold **...**
    while "**" in text:
        text = text.replace("**", "<strong>", 1)
        if "**" in text:
            text = text.replace("**", "</strong>", 1)
        else:
            text += "</strong>"
    # Inline code `...`
    parts = text.split("`")
    if len(parts) > 1:
        text = parts[0]
        for i, chunk in enumerate(parts[1:], 1):
            text += (f"<code>{chunk}</code>" if i % 2 == 1 else chunk)
    return text
