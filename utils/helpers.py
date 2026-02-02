from urllib.parse import urlparse

def domain(url: str) -> str:
    try:
        d = urlparse(url).netloc
        return d.replace("www.", "") if d else url
    except Exception:
        return url