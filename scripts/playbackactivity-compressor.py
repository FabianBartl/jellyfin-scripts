"""
...

---

License: MIT
Author: Fabian Bartl
Repository: https://github.com/FabianBartl/jellyfin-scripts
Last update: 2026-04-09
"""

import sqlite3
import datetime as dt
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Union, Optional, NoReturn, Callable
from pprint import pprint
import logging


logging.basicConfig(
    level = logging.DEBUG,
)
LOG = logging.getLogger(Path(__file__).stem)


@dataclass
class Retention:
    years:  int = -1
    months: int =  6
    weeks:  int =  4
    days:   int = 14
    hours:  int = 48

@dataclass
class Config:
    playback_activity_db: Path = Path(r"C:\Users\fabia\Repositories\jellyfin-scripts\data\playback_reporting - Kopie.db")
    jellyfin_db: Path = Path(r"C:\Users\fabia\Repositories\jellyfin-scripts\data\jellyfin - Kopie.db")
    retention: Retention = Retention()

CONFIG = Config()


def cap_playduration(
        pb_db_cur: sqlite3.Cursor,
        jf_db_cur: sqlite3.Cursor,
    ) -> int:
    """
    caps every playback entry to the runtime of the played item,
    but skips entries where PlaybackMethod is NULL
    
    note: this function does not automatically commits the updated playback durations
    """
    global LOG
    
    item_runtime = jf_db_cur.execute("""
        SELECT PresentationUniqueKey AS ItemId, RunTimeTicks / 10000000 AS RunTimeSec
        FROM BaseItems
        WHERE RunTimeTicks is NOT NULL
    """).fetchall()
    item_runtime_map = { i["ItemId"]: i["RunTimeSec"] for i in item_runtime }
    LOG.info("found %s base items with set runtime", len(item_runtime))
    
    capplaydur_items: list[tuple] = []
    for entry in pb_db_cur.execute("""
        SELECT ItemId, PlayDuration, PlaybackMethod, ItemType, ClientName
        FROM PlaybackActivity
        WHERE PlaybackMethod is not NULL
    """).fetchall():
        if (runtime_sec := item_runtime_map.get(entry["ItemId"])) != None:
            if entry["PlayDuration"] > runtime_sec:
                capplaydur_items.append((runtime_sec, entry["ItemId"]))
                
                if LOG.isEnabledFor(logging.DEBUG):
                    overlength_secs = entry["PlayDuration"] - runtime_sec
                    overlength_percentage = 100 / runtime_sec * overlength_secs
                    LOG.debug("capped playback duration of %ss of item id %s to runtime %ss (%ss=%s%%) [%s played a %s]", entry["PlayDuration"], entry["ItemId"], runtime_sec, overlength_secs, int(overlength_percentage), entry["ClientName"], entry["ItemType"])
                else:
                    LOG.info("capped playback duration of %ss of item id %s to runtime %ss", entry["PlayDuration"], entry["ItemId"], runtime_sec)
    
    updated_rowcount = pb_db_cur.executemany("""
        UPDATE PlaybackActivity
        SET PlayDuration = ?
        WHERE ItemId = ?
        AND PlaybackMethod is not NULL
    """, capplaydur_items).rowcount
    LOG.info("updated %s runtime entries of %s items", updated_rowcount, len(capplaydur_items))
    
    return updated_rowcount


def compress_activity_range(
        pb_db_cur: sqlite3.Cursor,
        _from: dt.datetime,
        to: dt.datetime,
    ) -> list[sqlite3.Row]:
    """
    compresses all playback activity per user per item in the given datetime range: _from <= activity < to
    
    note: this function does not automatically commits the deleted and inserted playback activities
    """
    global LOG

    from_datetimestr = _from.isoformat()
    to_datetimestr = to.isoformat()
    
    compressed_activity = pb_db_cur.execute("""
        SELECT UserId, ItemId, ItemType, ItemName, SUM(PlayDuration) AS TotalPlayDuration
        FROM PlaybackActivity
        WHERE datetime(DateCreated) >= datetime(?)
        AND datetime(DateCreated) < datetime(?)
        GROUP BY UserId, ItemId
    """, (from_datetimestr, to_datetimestr)).fetchall()
    LOG.info("compressed playback activity between %s and %s per user per item into %s entries", from_datetimestr, to_datetimestr, len(compressed_activity))

    deleted_activity_rowcount = pb_db_cur.execute("""
        DELETE
        FROM PlaybackActivity
        WHERE datetime(DateCreated) >= datetime(?)
        AND datetime(DateCreated) < datetime(?)
    """, (from_datetimestr, to_datetimestr)).rowcount
    LOG.info("deleted %s activity entries between %s and %s", deleted_activity_rowcount, from_datetimestr, to_datetimestr)
    
    inserted_activity_rowcount = pb_db_cur.executemany(f"""
        INSERT INTO PlaybackActivity
        VALUES (datetime('{from_datetimestr}'), :UserId, :ItemId, :ItemType, :ItemName, NULL, NULL, NULL, :TotalPlayDuration)
    """, compressed_activity).rowcount
    LOG.info("inserted %s compressed playback activities dated at %s", inserted_activity_rowcount, from_datetimestr)
    
    return compressed_activity


def step_backwards(
        datetimes: list[dt.datetime],
        cursor: dt.datetime,
        _from: dt.datetime,
        step: str,
        count: int,
    ) -> dt.datetime:
    """
    """
    global LOG
    
    start_len = len(datetimes)
    step = step.lower()
    
    iterations = 0
    while cursor > _from:
        if count != -1 and iterations >= count:
            break
        
        if step == "h":
            cursor = cursor.replace(minute=0, second=0, microsecond=0)
            datetimes.append(cursor)
            cursor -= dt.timedelta(hours=1)
        elif step == "d":
            cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
            datetimes.append(cursor)
            cursor -= dt.timedelta(days=1)
        elif step == "w":
            cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
            datetimes.append(cursor)
            cursor -= dt.timedelta(days=cursor.weekday() + 7)
        elif step == "m":
            cursor = cursor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            datetimes.append(cursor)
            if cursor.month == 1:
                cursor = cursor.replace(year=cursor.year-1, month=12)
            else:
                cursor = cursor.replace(month=cursor.month-1)
        elif step == "y":
            cursor = cursor.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            datetimes.append(cursor)
            cursor = cursor.replace(year=cursor.year-1)
        else:
            raise ValueError(f"unknown step type '{step}'")

        iterations += 1
    
    LOG.info("appended %s/%s datetime steps of 1%s length from %s to %s", iterations, count, step, datetimes[start_len], datetimes[-1])
    return cursor

def get_datetime_ranges(
        retention: Retention,
        _from: dt.datetime,
        to: dt.datetime,
    ) -> list[dt.datetime]:
    """
    creates a list of datetimes from latest to earliest, each datetime representing the start date of a retention period
    """
    global LOG
    
    _from = dt.datetime(_from.year-1, 1, 1)
    to = to.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    LOG.info("create datetime steps from %s to %s", _from, to)

    datetimes: list[dt.datetime] = []
    cursor: dt.datetime = to

    cursor = step_backwards(datetimes, cursor, _from, "h", retention.hours)
    cursor = step_backwards(datetimes, cursor, _from, "d", retention.days)
    cursor = step_backwards(datetimes, cursor, _from, "w", retention.weeks)
    cursor = step_backwards(datetimes, cursor, _from, "m", retention.months)
    cursor = step_backwards(datetimes, cursor, _from, "y", retention.years)

    return datetimes


def main() -> NoReturn:
    global CONFIG

    # load playback activity and jellyfin databases and create cursors
    # use sqlite3.Row instead of tuples for returns: https://docs.python.org/3/library/sqlite3.html#how-to-create-and-use-row-factories
    pb_db_conn = sqlite3.connect(CONFIG.playback_activity_db)
    pb_db_conn.row_factory = sqlite3.Row
    pb_db_cur = pb_db_conn.cursor()

    jf_db_conn = sqlite3.connect(CONFIG.jellyfin_db)
    jf_db_conn.row_factory = sqlite3.Row
    jf_db_cur = jf_db_conn.cursor()
    
    # cap playback duration of all entries to their specific runtime
    cap_playduration(pb_db_cur, jf_db_cur)
    pb_db_conn.commit()
    
    #
    minmax_datetime = pb_db_cur.execute("""
        SELECT MIN(datetime(DateCreated)) AS MinDateCreated, MAX(datetime(DateCreated)) AS MaxDateCreated
        FROM PlaybackActivity
    """).fetchone()
    min_datetime = dt.datetime.fromisoformat(minmax_datetime["MinDateCreated"])
    max_datetime = dt.datetime.fromisoformat(minmax_datetime["MaxDateCreated"])
    
    datetime_ranges = get_datetime_ranges(CONFIG.retention, min_datetime, max_datetime)
    
    for idx, current in enumerate(datetime_ranges[1:]):
        previous = datetime_ranges[idx]
        
        #
        compress_activity_range(pb_db_cur, current, previous)
        pb_db_conn.commit()

    # close all loaded databases
    pb_db_conn.close()
    jf_db_conn.close()



if __name__ == "__main__":
    main()
