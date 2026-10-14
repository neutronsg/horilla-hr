"""One Neutron email frame for built-in, automated and HR-composed messages."""

import logging
from email.mime.image import MIMEImage

from bs4 import BeautifulSoup
from django.contrib.staticfiles import finders
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)
BRAND_MARKER = 'data-neutron-email="true"'


def html_to_plain(html):
    """Retain action URLs in the accessible plain-text version."""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.find_all(["head", "style", "script"]):
        element.decompose()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        label = link.get_text(" ", strip=True)
        if href.startswith(("https://", "http://")):
            link.replace_with(f"{label}: {href}")
    return "\n".join(
        line.strip() for line in soup.get_text("\n").splitlines() if line.strip()
    )


def prepare_neutron_email(message):
    """Preserve envelope/attachments; add HTML + text and an embedded brand logo.

    Called immediately before SMTP delivery so ad-hoc and automation messages
    receive the same frame without changing user-authored content or routing.
    """
    html = None
    other_alternatives = []
    for alternative in getattr(message, "alternatives", []):
        content, mimetype = alternative
        if mimetype == "text/html":
            html = content
        else:
            other_alternatives.append((content, mimetype))
    if html is None and message.content_subtype == "html":
        html = message.body
    original_html = html
    if not html or BRAND_MARKER not in html:
        if html:
            soup = BeautifulSoup(html, "html.parser")
            html_content = soup.body.decode_contents() if soup.body else html
        else:
            html_content = ""
        html = render_to_string(
            "email/neutron_generic.html",
            {
                "subject": message.subject,
                "html_content": html_content,
                "content": message.body if message.content_subtype != "html" else "",
            },
        )
    # Keep authored plain text (especially reset links) instead of regenerating it.
    plain = (
        message.body
        if message.content_subtype != "html" and message.body != original_html
        else html_to_plain(html)
    )
    if not plain.strip():
        plain = html_to_plain(html)
    branded = EmailMultiAlternatives(
        subject=message.subject,
        body=plain,
        from_email=message.from_email,
        to=list(message.to),
        cc=list(message.cc),
        bcc=list(message.bcc),
        reply_to=list(message.reply_to or []),
        connection=message.connection,
        headers=dict(message.extra_headers),
        attachments=list(message.attachments),
    )
    branded.encoding = message.encoding
    branded.mixed_subtype = message.mixed_subtype
    for content, mimetype in other_alternatives:
        branded.attach_alternative(content, mimetype)
    branded.attach_alternative(html, "text/html")
    if not any(
        getattr(a, "get", lambda *_: None)("Content-ID") == "<neutron_logo>"
        for a in branded.attachments
    ):
        logo_path = finders.find("images/brand/neutron-email-logo.png")
        if logo_path:
            with open(logo_path, "rb") as logo_file:
                logo = MIMEImage(logo_file.read(), _subtype="png")
            logo.add_header("Content-ID", "<neutron_logo>")
            logo.add_header("Content-Disposition", "inline", filename="neutron.png")
            branded.attach(logo)
        else:
            # A readable wordmark remains if static files are unavailable.
            soup = BeautifulSoup(html, "html.parser")
            for image in soup.find_all("img", src="cid:neutron_logo"):
                wordmark = soup.new_tag(
                    "span", style="font-size:24px;font-weight:700;color:#051c97;"
                )
                wordmark.string = "Neutron"
                image.replace_with(wordmark)
            branded.alternatives = []
            for content, mimetype in other_alternatives:
                branded.attach_alternative(content, mimetype)
            branded.attach_alternative(str(soup), "text/html")
            logger.warning("Neutron email logo asset is unavailable")
    return branded
