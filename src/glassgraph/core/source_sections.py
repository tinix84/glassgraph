"""Shared legacy section and bullet patterns for curated source pages."""
import re

SUBSECTION_RE = re.compile(r"^###\s+.*mentioned", re.IGNORECASE)
KEY_EXTRACTIONS_RE = re.compile(r"^##\s+Key extractions", re.IGNORECASE)
H2_RE = re.compile(r"^##\s+")
BULLET_RE = re.compile(r"^-\s+\[\[([^\[\]\|]+?)(?:\|[^\[\]]+)?\]\]\s*[—-]\s*(.*)$")
