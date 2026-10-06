"""notify.py - известия за модела (ZADACHA_PAZACH_2, 06.10.2026, Дака).

Кой вика: features/layer_gate.py (решение на пазача, грешка в пазача), layer_weekly_cron.sh (грешка в преобучението или пазачът спря
неочаквано), web/model_admin.py (ръчно превключване от /admin/model).

Канал - от .env, чете се НАНОВО при всяко известие (Дака може да го включи/смени без рестарт):
  NOTIFY_CHANNEL=telegram  + TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  NOTIFY_CHANNEL=email     + SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, NOTIFY_TO   (порт 465 = SSL, иначе STARTTLS)
  SITE_URL=https://...     (по желание) - за пълен линк към /admin/model в известието
Без канал/данни - само ред в notify_log.txt, без грешка. ВСЯКО известие (изпратено или не) оставя ред в notify_log.txt.
send() никога не хвърля - известието не бива да спре пазача или страницата.

Пробно известие:  venv/bin/python3 notify.py --test
"""
import os
import sys
import json
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(ROOT, "notify_log.txt")
ADMIN_PATH = "/admin/model"


def read_env():
    """.env наново от диска (не от кеша на config при import) - празен речник при проблем."""
    try:
        sys.path.insert(0, ROOT)
        import config
        return config._load_env(config._ENV_PATH)
    except Exception:
        return {}


def _log(line, log_path):
    try:
        with open(log_path or LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {line}\n")
    except Exception:
        pass


def _telegram(env, text):
    token, chat = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return "не е изпратено: липсва TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID в .env"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15) as r:
        body = json.loads(r.read().decode("utf-8", "replace"))
    if not body.get("ok"):
        return f"ГРЕШКА telegram: {body.get('description', body)}"
    return "изпратено (telegram)"


def _email(env, text):
    need = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "NOTIFY_TO")
    miss = [k for k in need if not env.get(k)]
    if miss:
        return "не е изпратено: липсва в .env: " + ", ".join(miss)
    msg = EmailMessage()
    msg["Subject"] = text.splitlines()[0][:150]
    msg["From"] = env["SMTP_USER"]
    msg["To"] = env["NOTIFY_TO"]
    msg.set_content(text)
    port = int(env["SMTP_PORT"])
    if port == 465:
        s = smtplib.SMTP_SSL(env["SMTP_HOST"], port, timeout=20)
    else:
        s = smtplib.SMTP(env["SMTP_HOST"], port, timeout=20)
        s.starttls()
    try:
        s.login(env["SMTP_USER"], env["SMTP_PASS"])
        s.send_message(msg)
    finally:
        s.quit()
    return f"изпратено (email до {env['NOTIFY_TO']})"


def link(env=None):
    env = read_env() if env is None else env
    base = env.get("SITE_URL", "").rstrip("/")
    return base + ADMIN_PATH if base else f"{ADMIN_PATH} (в админската част на сайта)"


def send(text, env=None, log_path=None):
    """Праща text + линк към /admin/model по канала от .env. Връща кратък статус. Никога не хвърля.
    env/log_path - само за тестове (env={} -> нищо не се праща навън)."""
    try:
        env = read_env() if env is None else env
        full = f"{text}\n{link(env)}"
        ch = env.get("NOTIFY_CHANNEL", "").strip().lower()
        if ch == "telegram":
            status = _telegram(env, full)
        elif ch == "email":
            status = _email(env, full)
        elif ch:
            status = f"не е изпратено: непознат NOTIFY_CHANNEL={ch} (telegram или email)"
        else:
            status = "само в лога (няма NOTIFY_CHANNEL в .env)"
    except Exception as e:
        status = f"ГРЕШКА при изпращане: {type(e).__name__}: {e}"
        full = text
    _log(f"[{status}] " + full.replace("\n", " | "), log_path)
    return status


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--test" in a:
        print(send(f"Модел: пробно известие ({datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC) - ако го виждаш, каналът работи."))
    elif "--error" in a:                      # от layer_weekly_cron.sh
        print(send("Модел: ГРЕШКА - " + " ".join(a[a.index("--error") + 1:])))
    else:
        print(__doc__)
        sys.exit(1)
