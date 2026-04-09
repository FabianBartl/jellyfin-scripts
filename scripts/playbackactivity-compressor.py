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
from typing import Any, Union, Optional, NoReturn


@dataclass
class Retention:
    years:  int = -1
    months: int =  6
    weeks:  int =  5
    days:   int = 10

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
    caps every playback entry to the runtime of the played item
    
    note: this function does not automatically commits the updated playback durations
    """
    
    item_runtime = jf_db_cur.execute("""
        SELECT PresentationUniqueKey AS ItemId, RunTimeTicks / 10000000 AS RunTimeSec
        FROM BaseItems
        WHERE RunTimeTicks is NOT NULL
    """).fetchall()
    item_runtime_map = { i["ItemId"]: i["RunTimeSec"] for i in item_runtime }
    
    capplaydur_items: list[tuple] = []
    for entry in pb_db_cur.execute("""
        SELECT ItemId, PlayDuration
        FROM PlaybackActivity
    """).fetchall():
        if (runtime_sec := item_runtime_map.get(entry["ItemId"])) != None:
            if entry["PlayDuration"] > runtime_sec:
                capplaydur_items.append((runtime_sec, entry["ItemId"]))
    
    updated_rowcount = pb_db_cur.executemany("""
        UPDATE PlaybackActivity
        SET PlayDuration = ?
        WHERE ItemId = ?
    """, capplaydur_items).rowcount
    
    return updated_rowcount


def compress_activity(
        pb_db_cur: sqlite3.Cursor,
        retention: Retention,
    ) -> list[sqlite3.Row]:
    """
    compresses all playback activity per user per item into retention segments
    
    note: this function does not automatically commits the deleted and inserted playback activities
    """

    start_datestr = "2026-03-01"
    end_datestr = "2026-04-01"
    compressed_activity = pb_db_cur.execute("""
        SELECT UserId, ItemId, ItemType, ItemName, SUM(PlayDuration) AS TotalPlayDuration
        FROM PlaybackActivity
        WHERE DateCreated > date(?)
        AND DateCreated < date(?)
        GROUP BY UserId, ItemId
    """, (start_datestr, end_datestr)).fetchall()

    deleted_activity_rowcount = pb_db_cur.execute("""
        DELETE
        FROM PlaybackActivity
        WHERE DateCreated > date(?)
        AND DateCreated < date(?)
    """, (start_datestr, end_datestr)).rowcount
    
    inserted_activity_rowcount = pb_db_cur.executemany(f"""
        INSERT INTO PlaybackActivity
        VALUES (date('{start_datestr}'), :UserId, :ItemId, :ItemType, :ItemName, '', '', '', :TotalPlayDuration)
    """, compressed_activity).rowcount
    
    return compressed_activity


def main() -> NoReturn:
    global CONFIG

    # load playback activity and jellyfin databases and create cursors
    #  Use DictLike instead of Tuple for returns: sqlite3.Row
    #  https://docs.python.org/3/library/sqlite3.html#how-to-create-and-use-row-factories
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
    compress_activity(pb_db_cur, CONFIG.retention)
    pb_db_conn.commit()

    # close all loaded databases
    pb_db_conn.close()
    jf_db_conn.close()



if __name__ == "__main__":
    main()
