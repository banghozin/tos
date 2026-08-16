"""SQLite 저장소. 상품 최신 상태 + 관측 이력 + 쉐어링크 캐시."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "deals.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_id            INTEGER PRIMARY KEY,
    -- 링크 발급은 productId 가 아니라 tacaItemId 로 한다. 없으면 발급 불가.
    taca_id               INTEGER,
    taca_item_id          INTEGER,
    stock_id              INTEGER,
    display_name          TEXT,
    merchant_id           INTEGER,
    thumbnail_url         TEXT,
    original_price        INTEGER,
    display_price         INTEGER,
    discount_rate         INTEGER,
    coupon_discount       INTEGER,
    -- 쿠폰까지 반영한 실구매가. discountRate 에는 쿠폰이 빠져 있어 직접 계산한다.
    effective_price       INTEGER,
    effective_rate        INTEGER,
    is_lowest_30d         INTEGER,
    link_issuable         INTEGER,
    link_issue_reason     TEXT,
    is_sold_out           INTEGER,
    status                TEXT,
    review_score          REAL,
    review_count          INTEGER,
    page_view_count       INTEGER,
    campaign_end_at       TEXT,
    today_deal_end_at     TEXT,
    category_ids          TEXT,
    category_l1           INTEGER,   -- 최상위 카테고리. 사이트 필터용
    surface               TEXT,
    section_code          TEXT,
    rank                  INTEGER,
    first_seen_at         TEXT,
    last_seen_at          TEXT
);

-- 매 수집마다 한 줄. 가격 변동 추적용.
CREATE TABLE IF NOT EXISTS observations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id     INTEGER NOT NULL,
    observed_at    TEXT NOT NULL,
    display_price  INTEGER,
    original_price INTEGER,
    discount_rate  INTEGER,
    effective_price INTEGER,
    effective_rate  INTEGER,
    is_lowest_30d  INTEGER,
    is_sold_out    INTEGER,
    surface        TEXT,
    section_code   TEXT,
    rank           INTEGER
);
CREATE INDEX IF NOT EXISTS idx_obs_product ON observations(product_id, observed_at);

-- 쉐어링크는 상품당 영구 고정이므로 한 번 발급하면 재사용.
CREATE TABLE IF NOT EXISTS sharelinks (
    product_id  INTEGER PRIMARY KEY,
    short_url   TEXT NOT NULL,
    origin_url  TEXT,
    issued_at   TEXT NOT NULL
);

-- 카테고리 이름. API 의 CATEGORY_BEST 섹션 tabs 에서 얻는다.
CREATE TABLE IF NOT EXISTS categories (
    category_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL
);

-- 발행 이력. 같은 딜을 중복 발행하지 않기 위함.
CREATE TABLE IF NOT EXISTS published (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id    INTEGER NOT NULL,
    channel       TEXT NOT NULL,
    display_price INTEGER,
    published_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pub_product ON published(product_id, channel);

-- 상품이 어떤 섹션(TODAY_DEAL/BEST_SELLING 등)에 몇 위로 들어있는지.
-- products 는 dedup 으로 상품당 섹션 하나만 남기므로, 섹션별 랭킹을 보여주려면
-- 여기에 (섹션, 상품, 랭크)를 따로 저장해야 한다. 매 수집마다 통째로 갈아끼운다.
CREATE TABLE IF NOT EXISTS section_items (
    section_code TEXT NOT NULL,
    product_id   INTEGER NOT NULL,
    rank         INTEGER,
    PRIMARY KEY (section_code, product_id)
);
CREATE INDEX IF NOT EXISTS idx_section ON section_items(section_code, rank);
"""

PRODUCT_COLUMNS = [
    "product_id", "taca_id", "taca_item_id", "stock_id",
    "display_name", "merchant_id", "thumbnail_url",
    "original_price", "display_price", "discount_rate", "coupon_discount",
    "effective_price", "effective_rate",
    "is_lowest_30d", "link_issuable", "link_issue_reason", "is_sold_out",
    "status", "review_score", "review_count", "page_view_count",
    "campaign_end_at", "today_deal_end_at", "category_ids", "category_l1",
    "surface", "section_code", "rank",
]


# 스키마가 늘어나도 기존 DB를 버리지 않는다.
# sharelinks 는 재발급 비용이 크지 않더라도 이력이 사라지면 안 되는 자산이다.
MIGRATIONS = [
    ("products", "taca_id", "INTEGER"),
    ("products", "taca_item_id", "INTEGER"),
    ("products", "stock_id", "INTEGER"),
    ("products", "effective_price", "INTEGER"),
    ("products", "effective_rate", "INTEGER"),
    ("products", "category_l1", "INTEGER"),
    ("observations", "effective_price", "INTEGER"),
    ("observations", "effective_rate", "INTEGER"),
    ("sharelinks", "origin_url", "TEXT"),
]


def migrate(conn):
    for table, column, coltype in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    conn.commit()


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def upsert_product(conn, row, observed_at):
    """products는 최신 상태로 덮어쓰고, observations에는 항상 한 줄 추가."""
    cols = ", ".join(PRODUCT_COLUMNS)
    placeholders = ", ".join("?" for _ in PRODUCT_COLUMNS)
    # first_seen_at은 최초 1회만, last_seen_at은 매번 갱신
    updates = ", ".join(f"{c}=excluded.{c}" for c in PRODUCT_COLUMNS if c != "product_id")
    conn.execute(
        f"""INSERT INTO products ({cols}, first_seen_at, last_seen_at)
            VALUES ({placeholders}, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET {updates}, last_seen_at=excluded.last_seen_at""",
        [row.get(c) for c in PRODUCT_COLUMNS] + [observed_at, observed_at],
    )
    conn.execute(
        """INSERT INTO observations
           (product_id, observed_at, display_price, original_price, discount_rate,
            effective_price, effective_rate, is_lowest_30d, is_sold_out,
            surface, section_code, rank)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["product_id"], observed_at, row.get("display_price"),
            row.get("original_price"), row.get("discount_rate"),
            row.get("effective_price"), row.get("effective_rate"),
            row.get("is_lowest_30d"), row.get("is_sold_out"),
            row.get("surface"), row.get("section_code"), row.get("rank"),
        ),
    )


def prune_observations_before(conn, cutoff_iso):
    """cutoff_iso(ISO 문자열) 이전의 관측 이력을 삭제한다. 분기 보관/롤오버용.

    observed_at 은 전부 동일한 +09:00 오프셋 ISO 문자열이라 사전식 비교가 안전하다.
    (분기가 바뀌면 지난 분기 데이터가 지워져 가격 그래프가 새 분기 기준으로 초기화된다.)
    """
    cur = conn.execute("DELETE FROM observations WHERE observed_at < ?", (cutoff_iso,))
    conn.commit()
    return cur.rowcount


def clear_section_items(conn):
    """섹션 멤버십을 통째로 비운다. 매 수집 시작 때 호출해 현재 스냅샷으로 갈아끼운다."""
    conn.execute("DELETE FROM section_items")


def put_section_item(conn, section_code, product_id, rank):
    """(섹션, 상품, 랭크) 하나를 기록한다."""
    conn.execute(
        """INSERT INTO section_items (section_code, product_id, rank) VALUES (?, ?, ?)
           ON CONFLICT(section_code, product_id) DO UPDATE SET rank=excluded.rank""",
        (section_code, product_id, rank),
    )


def put_categories(conn, tabs):
    """[{'tabCode': '50995', 'displayName': '식품'}, ...] 를 저장한다."""
    for t in tabs:
        code, name = t.get("tabCode"), t.get("displayName")
        if not code or not name:
            continue
        conn.execute(
            """INSERT INTO categories (category_id, name) VALUES (?, ?)
               ON CONFLICT(category_id) DO UPDATE SET name=excluded.name""",
            (int(code), name),
        )


def get_sharelink(conn, product_id):
    r = conn.execute(
        "SELECT short_url FROM sharelinks WHERE product_id = ?", (product_id,)
    ).fetchone()
    return r["short_url"] if r else None


def put_sharelink(conn, product_id, short_url, issued_at, origin_url=None):
    conn.execute(
        """INSERT INTO sharelinks (product_id, short_url, origin_url, issued_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(product_id) DO UPDATE SET
               short_url=excluded.short_url, origin_url=excluded.origin_url""",
        (product_id, short_url, origin_url, issued_at),
    )
