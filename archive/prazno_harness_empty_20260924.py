# Само за доклада: същата тестова среда, но снимката се "вижда" празна в
# 14-дневния прозорец (нищо не се пипа в базата) - за текста "още не са изчислени".
import sys, system_tracker as st
st.get_snapshot_rows_for_date_range = lambda a, b: []
exec(open("/home/inkas/sportbg-predictor/archive/prazno_harness_20260924.py", encoding="utf-8").read())
