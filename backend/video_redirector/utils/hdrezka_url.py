import re
from urllib.parse import urlparse, urlunparse


_HDREZKA_HOST_PATTERN = re.compile(r"^(?:www\.)?(?:hd)?rezka(?:-ua)?\.(?:ag|co|me|org|net|com)$", re.IGNORECASE)


def sanitize_hdrezka_url(raw_url: str) -> str:

	if not raw_url:
		return raw_url

	url = raw_url.strip()
	# Strip leading @ that sometimes appears when copying from Telegram
	if url.startswith("@"):
		url = url[1:]

	parsed = urlparse(url)

	# Normalize host to canonical domain if it's a rezka variant
	host = (parsed.netloc or "").lower()
	if host.startswith("www."):
		host = host[4:]

	if _HDREZKA_HOST_PATTERN.match(host):
		host = "hdrezka.ag"

	# Force https
	scheme = "https"

	# Drop query and fragment
	path = parsed.path or ""
	# Remove trailing slash (keep root as is)
	if path.endswith("/") and len(path) > 1:
		path = path[:-1]

	# Ensure path looks normalized; keep as-is otherwise
	normalized = urlunparse((scheme, host, path, "", "", ""))
	return normalized


