from urllib.parse import urlparse, urlunparse


def get_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def normalize_url(url: str) -> str:
    """Key used to de-duplicate results (ignores fragment, trailing slash, scheme and www)."""
    parts = urlparse(url)
    path = parts.path.rstrip("/") or "/"
    return urlunparse(("", get_domain(url), path, "", parts.query, ""))


def domain_matches(domain: str, patterns: list[str]) -> bool:
    """True if `domain` equals or is a subdomain of any pattern."""
    for pattern in patterns:
        pattern = pattern.lower().removeprefix("www.").strip()
        if pattern and (domain == pattern or domain.endswith("." + pattern)):
            return True
    return False


def is_trusted(domain: str, patterns: list[str]) -> bool:
    """A trusted source: listed (or a subdomain), or - for the patterns "gov" / "edu" - any government / university
    domain (nasa.gov, india.gov.in, moh.gov.om, mit.edu, du.edu.om; ox.ac.uk is not covered: list it)."""
    special = {p for p in patterns if p in ("gov", "edu")}
    if special & set(domain.lower().split(".")):
        return True
    return domain_matches(domain, [p for p in patterns if p not in special])
