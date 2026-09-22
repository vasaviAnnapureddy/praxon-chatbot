"""
The lead alert email, sent through Resend's HTTP API.

Why Resend and not Gmail SMTP: Render's free plan blocks outbound SMTP ports.
Gmail would not error loudly — it would just hang and time out, and you would
discover on pitch day that no alert ever arrived. Resend goes over plain HTTPS,
which Render allows.

Why httpx and not the resend SDK: it is one POST request. A whole dependency
for one POST is not worth the megabytes on a 512 MB box.

Free-tier limitation to remember: until a domain is verified, Resend will only
deliver to the email address you signed up with. That is fine for the demo (the
alerts come to you). When Praxon has a domain, verify it in Resend and change
ALERT_FROM_EMAIL / ALERT_TO_EMAIL — no code change.
"""

from __future__ import annotations

import html

import httpx

from app.config import get_company, settings
from app.core.logging import get_logger
from app.core.timezone import to_ist_string
from app.leads.stages import label_description

log = get_logger("notify")

RESEND_URL = "https://api.resend.com/emails"


def _row(label: str, value: str) -> str:
    if not value:
        value = '<span style="color:#9aa3b2">not shared</span>'
    else:
        value = html.escape(str(value))
    return (
        '<tr>'
        f'<td style="padding:8px 14px;color:#5B6577;font-size:13px;white-space:nowrap">{label}</td>'
        f'<td style="padding:8px 14px;color:#10182B;font-size:14px;font-weight:600">{value}</td>'
        '</tr>'
    )


def _build_html(lead, conversation, messages) -> str:  # noqa: ANN001
    company = get_company()
    primary = company.get("branding.primary_color", "#1F4FD8")

    transcript = "".join(
        f'<div style="margin:6px 0"><span style="color:{"#1F4FD8" if m.role == "user" else "#5B6577"};'
        f'font-weight:600">{"Visitor" if m.role == "user" else "Assistant"}:</span> '
        f'<span style="color:#10182B">{html.escape(m.content[:600])}</span></div>'
        for m in messages[-14:]
    )

    contact_bits = []
    if lead.email:
        contact_bits.append(f'<a href="mailto:{html.escape(lead.email)}">{html.escape(lead.email)}</a>')
    if lead.phone:
        contact_bits.append(f'<a href="tel:+91{html.escape(lead.phone)}">+91 {html.escape(lead.phone)}</a>')
    contact_html = " &nbsp;•&nbsp; ".join(contact_bits) or "not shared"

    wa = ""
    if lead.phone:
        wa = (
            f'<a href="https://wa.me/91{lead.phone}" '
            f'style="display:inline-block;margin-top:14px;background:{primary};color:#fff;'
            f'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600">'
            f'WhatsApp them</a>'
        )

    contact_row = (
        '<tr><td style="padding:8px 14px;color:#5B6577;font-size:13px">Contact</td>'
        f'<td style="padding:8px 14px;font-size:14px;font-weight:600">{contact_html}</td></tr>'
    )

    return f"""<!doctype html>
<html><body style="margin:0;background:#F5F7FB;font-family:'Segoe UI',system-ui,sans-serif">
  <div style="max-width:620px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;
              border:1px solid #E4E8F0">
    <div style="background:{primary};color:#fff;padding:18px 22px">
      <div style="font-size:13px;opacity:.85;letter-spacing:.4px">NEW ENQUIRY — {html.escape(company.name)}</div>
      <div style="font-size:20px;font-weight:700;margin-top:4px">
        {html.escape(lead.name or "Someone")} left their details
      </div>
    </div>

    <table style="width:100%;border-collapse:collapse;margin:10px 0">
      {contact_row}
      {_row("Name", lead.name)}
      {_row("Company", lead.company_name)}
      {_row("Wants", lead.requirement)}
      {_row("Budget said", lead.budget)}
      {_row("Timeline said", lead.timeline_raw)}
      {_row("Timeline label", f"{lead.timeline_label} — {label_description(lead.timeline_label)}")}
      {_row("Arrived", to_ist_string(lead.created_at))}
    </table>

    <div style="padding:0 22px 6px">{wa}</div>

    <div style="padding:16px 22px;border-top:1px solid #EEF1F6;margin-top:10px">
      <div style="font-size:12px;color:#5B6577;text-transform:uppercase;letter-spacing:.5px;
                  margin-bottom:8px">Conversation</div>
      <div style="font-size:13px;line-height:1.55">{transcript}</div>
    </div>

    <div style="padding:14px 22px;background:#F8FAFD;font-size:12px;color:#5B6577;line-height:1.5">
      This is a factual summary of what the visitor said. The assistant does not score or rank
      enquiries — that call is yours.
    </div>
  </div>
</body></html>"""


def _build_text(lead) -> str:  # noqa: ANN001
    return "\n".join(
        [
            f"New enquiry — {get_company().name}",
            "",
            f"Name:      {lead.name or '-'}",
            f"Company:   {lead.company_name or '-'}",
            f"Email:     {lead.email or '-'}",
            f"Phone:     {lead.phone or '-'}",
            f"Wants:     {lead.requirement or '-'}",
            f"Budget:    {lead.budget or '-'}",
            f"Timeline:  {lead.timeline_raw or '-'} ({lead.timeline_label})",
            f"Arrived:   {to_ist_string(lead.created_at)}",
        ]
    )


async def send_lead_alert(lead, conversation, messages) -> bool:  # noqa: ANN001
    if not settings.ALERTS_ENABLED:
        log.info("alerts disabled — skipping email for lead %s", lead.id)
        return False
    if not settings.RESEND_API_KEY or not settings.ALERT_TO_EMAIL:
        log.warning("RESEND_API_KEY or ALERT_TO_EMAIL missing — no alert sent")
        return False

    company = get_company()
    who = lead.name or lead.email or lead.phone or "someone"
    subject = f"New enquiry — {who} ({lead.timeline_label})"

    payload = {
        "from": f"{company.name} Assistant <{settings.ALERT_FROM_EMAIL}>",
        "to": [settings.ALERT_TO_EMAIL],
        "subject": subject,
        "html": _build_html(lead, conversation, messages),
        "text": _build_text(lead),
    }
    if lead.email:
        payload["reply_to"] = lead.email

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code in (200, 201):
            log.info("lead alert sent for lead %s", lead.id)
            return True
        log.error("resend rejected the alert (%s): %s", resp.status_code, resp.text[:300])
        return False
    except Exception as exc:  # noqa: BLE001
        # Never let a failed email break anything. The lead is already saved.
        log.error("alert email failed: %s", exc)
        return False


async def send_access_request_alert(req) -> bool:  # noqa: ANN001
    """Tells the owner someone asked for a client login. Plain text: it is a nudge, not a report."""
    if not (settings.ALERTS_ENABLED and settings.RESEND_API_KEY and settings.ALERT_TO_EMAIL):
        return False
    company = get_company()
    body = "\n".join(
        [
            "Someone asked for a client login on your website.",
            "",
            f"Name:     {req.name}",
            f"Email:    {req.email}",
            f"Company:  {req.company_name or '-'}",
            f"Message:  {req.message or '-'}",
            "",
            "Approve or reject it in the dashboard -> Requests tab.",
            "Nothing happens until someone on the team approves it.",
        ]
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": f"{company.name} Assistant <{settings.ALERT_FROM_EMAIL}>",
                    "to": [settings.ALERT_TO_EMAIL],
                    "subject": f"Access request — {req.name}",
                    "text": body,
                    "reply_to": req.email,
                },
            )
        if resp.status_code in (200, 201):
            return True
        log.error("resend rejected the access-request alert (%s): %s", resp.status_code, resp.text[:300])
    except Exception as exc:  # noqa: BLE001 — the request is already saved
        log.error("access-request email failed: %s", exc)
    return False


async def send_sign_in_email(user, temp_password: str, sign_in_url: str) -> tuple[bool, str]:  # noqa: ANN001
    """
    Emails a new person their sign-in details: the link, their email, and the
    TEMPORARY password. Returns (sent?, a sentence for the dashboard).

      Q: Is it safe to email a password?
      A: This one is. It works once, dies in 7 days, and the first thing it
         opens is "choose your own password". The real password is never emailed.
    """
    if not settings.RESEND_API_KEY:
        return False, "Email isn't set up (RESEND_API_KEY is empty). Copy the message instead."
    if not user.email:
        return False, "This account has no email address."

    company = get_company()
    who = user.name or "there"
    text = "\n".join(
        [
            f"Hi {who},",
            "",
            f"Your {company.name} account is ready.",
            "",
            f"Sign in at:          {sign_in_url}",
            f"Email:               {user.email}",
            f"Temporary password:  {temp_password}",
            "",
            "When you first sign in you'll choose your own password.",
            "This temporary password stops working after 7 days.",
            "",
            "If you weren't expecting this, just ignore it or reply to let us know.",
            "",
            f"— {company.name}",
        ]
    )
    e = html.escape
    body = f"""<div style="font-family:Arial,sans-serif;max-width:520px;color:#10182B;line-height:1.5">
      <p>Hi {e(who)},</p>
      <p>Your <b>{e(company.name)}</b> account is ready.</p>
      <table style="border-collapse:collapse;margin:12px 0">
        <tr><td style="padding:4px 12px 4px 0;color:#5B6478">Email</td><td><b>{e(user.email)}</b></td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#5B6478">Temporary password</td>
            <td><code style="font-size:16px;background:#F3F6FC;padding:3px 8px;border-radius:6px">{e(temp_password)}</code></td></tr>
      </table>
      <p><a href="{e(sign_in_url)}" style="display:inline-block;background:#1F4FD8;color:#fff;padding:10px 18px;
         border-radius:8px;text-decoration:none">Sign in</a></p>
      <p style="color:#5B6478;font-size:13px">When you first sign in you'll choose your own password.
         This temporary password stops working after 7 days. If you weren't expecting this, ignore it
         or reply to let us know.</p>
    </div>"""

    payload = {
        "from": f"{company.name} <{settings.ALERT_FROM_EMAIL}>",
        "to": [user.email],
        "subject": f"Your {company.name} sign-in details",
        "html": body,
        "text": text,
    }
    if settings.ALERT_TO_EMAIL:
        payload["reply_to"] = settings.ALERT_TO_EMAIL        # their reply reaches you, not a robot
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                RESEND_URL, headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"}, json=payload
            )
    except Exception as exc:  # noqa: BLE001 — the account is already made; only the email failed
        log.error("sign-in email failed: %s", exc)
        return False, "Couldn't reach the email service. Copy the message instead."
    if resp.status_code in (200, 201):
        return True, f"Emailed to {user.email}"
    #   Q: Why a special message for 403?
    #   A: On Resend's free plan without a verified domain, 403 means "you can
    #      only email your OWN address". That is the usual reason — say it plainly.
    log.warning("resend refused the sign-in email (%s): %s", resp.status_code, resp.text[:200])
    if resp.status_code == 403:
        return False, (
            "Not emailed: Resend's free plan only sends to your own address until you verify "
            "a domain. Copy the message below and send it yourself."
        )
    try:
        reason = str(resp.json().get("message", ""))[:200]
    except ValueError:
        reason = ""
    return False, f"Not emailed — {reason or f'Resend said {resp.status_code}'} Copy the message instead."


async def send_test_email(to_address: str = "") -> tuple[bool, str]:
    """Used by scripts and the admin dashboard to prove Resend is wired up."""
    target = to_address or settings.ALERT_TO_EMAIL
    if not settings.RESEND_API_KEY:
        return False, "RESEND_API_KEY is empty in backend/.env"
    if not target:
        return False, "No destination address (ALERT_TO_EMAIL is empty)"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": f"{get_company().name} Assistant <{settings.ALERT_FROM_EMAIL}>",
                    "to": [target],
                    "subject": "Test — chatbot alerts are working",
                    "text": "If you are reading this, Resend is configured correctly.",
                },
            )
        if resp.status_code in (200, 201):
            return True, f"Sent to {target}"
        return False, f"Resend said {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
