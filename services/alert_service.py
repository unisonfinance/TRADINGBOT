"""
Alert Service — Telegram and Email notifications for trade events.
Reads user preferences from Firestore and dispatches alerts.
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

logger = logging.getLogger(__name__)


class AlertService:
    """Sends alerts via Telegram and/or Email based on user preferences."""

    def __init__(self, alert_settings: dict = None):
        self.settings = alert_settings or {}

    # ── Telegram ──────────────────────────────────────────────

    def send_telegram(self, message: str) -> bool:
        """Send a Telegram message using Bot API."""
        bot_token = self.settings.get("telegram_bot_token", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = self.settings.get("telegram_chat_id", "") or os.environ.get("TELEGRAM_CHAT_ID", "")

        if not bot_token or not chat_id:
            logger.debug("Telegram not configured — skipping")
            return False

        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }, timeout=10)
            if resp.status_code == 200:
                logger.info("Telegram alert sent")
                return True
            else:
                logger.warning("Telegram send failed: %s", resp.text[:200])
                return False
        except Exception as e:
            logger.error("Telegram error: %s", e)
            return False

    # ── Email ─────────────────────────────────────────────────

    def send_email(self, subject: str, body: str) -> bool:
        """Send an email alert via SMTP."""
        smtp_host = self.settings.get("smtp_host", "") or os.environ.get("SMTP_HOST", "")
        smtp_port = int(self.settings.get("smtp_port", 587) or os.environ.get("SMTP_PORT", 587))
        smtp_user = self.settings.get("smtp_user", "") or os.environ.get("SMTP_USER", "")
        smtp_pass = self.settings.get("smtp_pass", "") or os.environ.get("SMTP_PASS", "")
        to_email = self.settings.get("alert_email", "") or os.environ.get("ALERT_EMAIL", "")

        if not smtp_host or not smtp_user or not to_email:
            logger.debug("Email not configured — skipping")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = to_email
            msg.attach(MIMEText(body, "html"))

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            logger.info("Email alert sent to %s", to_email)
            return True
        except Exception as e:
            logger.error("Email error: %s", e)
            return False

    # ── Dispatch (send to all configured channels) ────────────

    def send_trade_alert(self, trade_data: dict):
        """Send a trade execution alert to all configured channels."""
        side = trade_data.get("side", "UNKNOWN")
        symbol = trade_data.get("symbol", "?")
        price = trade_data.get("price", 0)
        size = trade_data.get("size", 0)
        strategy = trade_data.get("strategy", "?")
        pnl = trade_data.get("pnl", None)

        emoji = "🟢" if side == "BUY" else "🔴"
        pnl_line = f"\n💰 P&L: ${pnl:.4f}" if pnl is not None else ""

        telegram_msg = (
            f"{emoji} <b>{side}</b> {symbol}\n"
            f"📊 Strategy: {strategy}\n"
            f"💲 Price: ${price:.4f}\n"
            f"📦 Size: {size:.6f}"
            f"{pnl_line}"
        )

        email_body = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: {'#10b981' if side == 'BUY' else '#ef4444'};">
                {emoji} {side} — {symbol}
            </h2>
            <table style="border-collapse: collapse; width: 100%;">
                <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><b>Strategy</b></td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">{strategy}</td></tr>
                <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><b>Price</b></td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">${price:.4f}</td></tr>
                <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><b>Size</b></td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">{size:.6f}</td></tr>
                {'<tr><td style="padding: 8px;"><b>P&L</b></td><td style="padding: 8px;">${:.4f}</td></tr>'.format(pnl) if pnl is not None else ''}
            </table>
            <p style="color: #888; font-size: 12px; margin-top: 16px;">TrekBot Alert System</p>
        </div>
        """

        # Check user preferences
        if self.settings.get("telegram_enabled", True):
            self.send_telegram(telegram_msg)

        if self.settings.get("email_enabled", False):
            self.send_email(f"TrekBot: {side} {symbol}", email_body)

    def send_bot_alert(self, event: str, details: str = ""):
        """Send a bot lifecycle alert (started, stopped, error)."""
        icons = {"started": "🚀", "stopped": "🛑", "error": "⚠️"}
        icon = icons.get(event, "ℹ️")

        telegram_msg = f"{icon} <b>Bot {event.upper()}</b>\n{details}"
        email_body = f"<h2>{icon} Bot {event.upper()}</h2><p>{details}</p>"

        if self.settings.get("telegram_enabled", True):
            self.send_telegram(telegram_msg)
        if self.settings.get("email_enabled", False):
            self.send_email(f"TrekBot: Bot {event}", email_body)

    def send_scanner_alert(self, signals: list):
        """Send multi-pair scanner signal alerts."""
        if not signals:
            return

        lines = []
        for s in signals:
            emoji = "🟢" if s.get("signal") == "BUY" else "🔴" if s.get("signal") == "SELL" else "⚪"
            lines.append(f"{emoji} {s.get('symbol', '?')}: {s.get('signal', 'HOLD')} ({s.get('strategy', '?')})")

        telegram_msg = "📡 <b>Scanner Signals</b>\n" + "\n".join(lines)

        if self.settings.get("telegram_enabled", True):
            self.send_telegram(telegram_msg)
