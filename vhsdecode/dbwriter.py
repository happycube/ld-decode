from sqlite3 import Connection


class DBWriter:
    """Class for unifying sqlite writing between cvbs and vhs. Currently doesn't store anything."""

    def __init__(self):
        pass

    @staticmethod
    def write_field(
        field_data: dict, db_connection: Connection, capture_id: int, do_dod
    ):
        field_id = field_data["seqNo"] - 1

        decodeFaults = (
            None
            if field_data.get("decodeFaults") == 0
            else field_data.get("decodeFaults")
        )

        # Insert parent record into 'field_record'
        # We cast booleans to int because of the CHECK (val IN (0,1)) constraint
        db_connection.execute(
            """
            INSERT INTO field_record (
                capture_id, field_id, is_first_field, sync_conf, disk_loc,
                file_loc, field_phase_id, decode_faults,
                pad
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                capture_id,
                field_id,
                int(field_data["isFirstField"]),
                field_data["syncConf"],
                field_data["diskLoc"],
                field_data["fileLoc"],
                field_data["fieldPhaseID"],
                decodeFaults,
                0,
            ),
        )

        w_snr = field_data["vitsMetrics"].get("wSNR", 0)
        b_psnr = field_data["vitsMetrics"].get("bPSNR", 0)

        db_connection.execute(
            """
            INSERT INTO vits_metrics (
                capture_id, field_id, w_snr, b_psnr
            ) VALUES (?, ?, ?, ?)""",
            (capture_id, field_id, w_snr, b_psnr),
        )

        # Insert VBI data if present
        vbi_data = field_data.get("vbi", {}).get("vbiData", [])
        if vbi_data:
            # Ensure we have exactly 3 values for the vbi0, vbi1, vbi2 columns
            # This pads with 0 if fewer than 3 are found
            vbi_row = (vbi_data + [0, 0, 0])[:3]

            db_connection.execute(
                """
                INSERT INTO vbi (
                    capture_id, field_id, vbi0, vbi1, vbi2
                ) VALUES (?, ?, ?, ?, ?)""",
                (capture_id, field_id, vbi_row[0], vbi_row[1], vbi_row[2]),
            )

        # Insert dropouts (if any) into 'drop_outs'
        if do_dod and field_data.get("dropOuts"):
            dropout_lines = field_data["dropOuts"]["fieldLine"]
            dropout_starts = field_data["dropOuts"]["startx"]
            dropout_ends = field_data["dropOuts"]["endx"]

            # Use executemany for cleaner/faster insertion of multiple rows
            dropout_data = [
                (capture_id, field_id, line, start, end)
                for line, start, end in zip(dropout_lines, dropout_starts, dropout_ends)
            ]

            db_connection.executemany(
                """
                INSERT INTO drop_outs (
                    capture_id, field_id, field_line, startx, endx
                ) VALUES (?, ?, ?, ?, ?)""",
                dropout_data,
            )
        # Skip committing for now it's called again afterwards in build_sqlite_metadata
        # db_connection.commit()
