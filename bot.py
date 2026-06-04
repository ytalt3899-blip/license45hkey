"""
bot.py — Discord bot + license server (runs free on Render/Railway/Koyeb)

pip install discord.py flask requests

Environment variables (set in Render dashboard):
    DISCORD_TOKEN   — your bot token
    ADMIN_ROLE_ID   — Discord role ID allowed to use admin commands
    SECRET_KEY      — shared secret between tool and bot (any random string)
    PORT            — set automatically by Render (default 10000)

Run: python bot.py
"""

import os
import json
import hashlib
import secrets
import string
import threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template_string, redirect, session
import discord
from discord import app_commands
from discord.ext import commands

# ─────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────
DISCORD_TOKEN  = os.environ.get("DISCORD_TOKEN", "")
ADMIN_ROLE_ID  = int(os.environ.get("ADMIN_ROLE_ID", "0"))
SECRET_KEY     = os.environ.get("SECRET_KEY", "change_this_secret")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
PORT           = int(os.environ.get("PORT", 10000))
DB_FILE        = "licenses.json"

# ─────────────────────────────────────────────────────────────
#  DATABASE  (flat JSON — good enough for <1000 buyers)
# ─────────────────────────────────────────────────────────────

_db_lock = threading.Lock()

def load_db() -> dict:
    if os.path.isfile(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}

def save_db(db: dict):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def normalise_key(key: str) -> str:
    return key.strip().replace("-", "").upper()

def generate_key() -> str:
    chars = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(chars) for _ in range(16))
    return "-".join(raw[i:i+4] for i in range(0, 16, 4))

# ─────────────────────────────────────────────────────────────
#  FLASK  (HTTP endpoint the tool calls)
# ─────────────────────────────────────────────────────────────

flask_app = Flask(__name__)
flask_app.secret_key = os.environ.get("FLASK_SECRET", secrets.token_hex(24))

# ─────────────────────────────────────────────────────────────
#  HTML TEMPLATES
# ─────────────────────────────────────────────────────────────

_BASE_CSS = """
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:#0a0a12;color:#e0e0f0;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#12122a;border:1px solid #2a2a4a;border-radius:12px;padding:32px;width:100%;max-width:480px;box-shadow:0 0 40px rgba(176,110,243,0.1)}
.card.wide{max-width:800px}
h1{color:#c084fc;font-size:20px;margin-bottom:4px;letter-spacing:0.5px}
.sub{color:#5a5880;font-size:12px;margin-bottom:24px}
label{display:block;font-size:11px;color:#5a5880;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:5px}
input,select{width:100%;padding:10px 13px;background:#0a0a18;border:1px solid #2a2a4a;border-radius:7px;color:#e0e0f0;font-size:13px;margin-bottom:14px;outline:none}
input:focus{border-color:#b06ef3}
.btn{width:100%;padding:11px;background:linear-gradient(135deg,#7c3aed,#b06ef3);border:none;border-radius:7px;color:white;font-size:13px;font-weight:600;cursor:pointer;letter-spacing:0.3px}
.btn:hover{filter:brightness(1.1)}
.btn-sm{width:auto;padding:6px 14px;font-size:12px;border-radius:5px;display:inline-block}
.btn-red{background:linear-gradient(135deg,#c0392b,#e74c3c)}
.btn-green{background:linear-gradient(135deg,#1a7a4a,#27ae60)}
.btn-blue{background:linear-gradient(135deg,#1a4a7a,#2980b9)}
.error{background:rgba(255,23,68,0.1);border:1px solid rgba(255,23,68,0.3);border-radius:6px;padding:10px 14px;font-size:12px;color:#ff5270;margin-bottom:14px}
.success{background:rgba(0,230,118,0.1);border:1px solid rgba(0,230,118,0.3);border-radius:6px;padding:10px 14px;font-size:12px;color:#00e676;margin-bottom:14px}
.key-box{background:#0a0a18;border:1px solid #b06ef3;border-radius:8px;padding:14px 18px;font-family:monospace;font-size:18px;letter-spacing:2px;color:#c084fc;text-align:center;margin:16px 0;word-break:break-all}
.info-row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1e1e3a;font-size:13px}
.info-row:last-child{border-bottom:none}
.info-label{color:#5a5880}
.info-value{color:#e0e0f0;font-family:monospace;font-size:12px}
.badge{padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;text-transform:uppercase}
.badge-green{background:rgba(0,230,118,0.15);color:#00e676;border:1px solid rgba(0,230,118,0.3)}
.badge-red{background:rgba(255,23,68,0.15);color:#ff5270;border:1px solid rgba(255,23,68,0.3)}
.badge-yellow{background:rgba(255,171,64,0.15);color:#ffab40;border:1px solid rgba(255,171,64,0.3)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:8px 10px;color:#5a5880;border-bottom:1px solid #2a2a4a;text-transform:uppercase;font-size:10px;letter-spacing:0.8px}
td{padding:9px 10px;border-bottom:1px solid #1e1e3a;font-family:monospace}
tr:hover td{background:rgba(176,110,243,0.04)}
.nav{display:flex;gap:10px;margin-bottom:20px}
.copy-btn{background:rgba(176,110,243,0.15);border:1px solid rgba(176,110,243,0.3);border-radius:5px;color:#c084fc;padding:4px 12px;font-size:11px;cursor:pointer}
.copy-btn:hover{background:rgba(176,110,243,0.25)}
</style>
"""

LOGIN_TEMPLATE = _BASE_CSS + """
<div class="card">
  <h1>🔑 License Portal</h1>
  <p class="sub">Token Generator · Customer Dashboard</p>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST" action="/dashboard/login">
    <label>Username</label>
    <input name="username" placeholder="Your username" autocomplete="off" required>
    <label>Password</label>
    <input type="password" name="password" placeholder="Your password" required>
    <button class="btn" type="submit">Log In</button>
  </form>
  <p style="text-align:center;margin-top:16px;font-size:11px;color:#3a3860">
    Contact support if you forgot your credentials
  </p>
</div>
"""

DASHBOARD_TEMPLATE = _BASE_CSS + """
<div class="card" style="max-width:560px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <h1>🔑 Your License</h1>
    <a href="/dashboard/logout" style="font-size:11px;color:#5a5880;text-decoration:none">Log out</a>
  </div>
  <p class="sub">Token Generator · Customer Dashboard</p>

  <div class="key-box" id="keybox">{{ key }}</div>
  <div style="text-align:center;margin-bottom:16px">
    <button class="copy-btn" onclick="navigator.clipboard.writeText('{{ key }}');this.textContent='Copied ✓'">
      Copy Key
    </button>
  </div>

  <div style="background:#0a0a18;border-radius:8px;padding:14px 16px;border:1px solid #1e1e3a">
    <div class="info-row">
      <span class="info-label">Status</span>
      <span>{% if revoked %}<span class="badge badge-red">Revoked</span>
            {% elif activated %}<span class="badge badge-green">Active</span>
            {% else %}<span class="badge badge-yellow">Not Activated</span>{% endif %}</span>
    </div>
    <div class="info-row">
      <span class="info-label">HWID Bound</span>
      <span class="info-value">{{ "Yes" if hwid_bound else "No — binds on first launch" }}</span>
    </div>
    <div class="info-row">
      <span class="info-label">Activated</span>
      <span class="info-value">{{ activated_at or "Never" }}</span>
    </div>
    <div class="info-row">
      <span class="info-label">Last Seen</span>
      <span class="info-value">{{ last_seen or "Never" }}</span>
    </div>
  </div>

  <p style="margin-top:18px;font-size:11px;color:#3a3860;text-align:center">
    Your key is bound to your hardware on first use.<br>
    Contact support to transfer to a new machine.
  </p>
</div>
"""

ADMIN_TEMPLATE = _BASE_CSS + """
<div class="card wide">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <h1>⚙ Admin Panel</h1>
    <a href="/dashboard/logout" style="font-size:11px;color:#5a5880;text-decoration:none">Log out</a>
  </div>
  <p class="sub">License Management</p>

  {% if msg %}<div class="{{ msg_type }}">{{ msg }}</div>{% endif %}

  <!-- Add Key -->
  <div style="background:#0a0a18;border-radius:8px;padding:16px;border:1px solid #1e1e3a;margin-bottom:20px">
    <div style="font-size:12px;color:#c084fc;margin-bottom:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.8px">Add License Key</div>
    <form method="POST" action="/dashboard/admin/add" style="display:flex;gap:8px;flex-wrap:wrap">
      <input name="discord_id" placeholder="Discord ID (optional)" style="flex:1;min-width:180px;margin-bottom:0">
      <input name="username" placeholder="Username (buyer login)" style="flex:1;min-width:150px;margin-bottom:0" required>
      <input name="password" placeholder="Password" style="flex:1;min-width:130px;margin-bottom:0" required>
      <button class="btn btn-sm btn-green" type="submit">Add Key</button>
    </form>
    {% if new_key %}
    <div class="key-box" style="margin-top:12px;font-size:14px">{{ new_key }}</div>
    {% endif %}
  </div>

  <!-- Key table -->
  <table>
    <thead>
      <tr>
        <th>Key</th><th>Username</th><th>Status</th><th>HWID</th><th>Mismatches</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>
    {% for row in keys %}
      <tr>
        <td>{{ row.display }}</td>
        <td>{{ row.username or "—" }}</td>
        <td>{% if row.revoked %}<span class="badge badge-red">Revoked</span>
            {% elif row.activated %}<span class="badge badge-green">Active</span>
            {% else %}<span class="badge badge-yellow">Unused</span>{% endif %}</td>
        <td>{{ "Bound" if row.hwid_bound else "—" }}</td>
        <td style="color:{% if row.mismatches > 0 %}#ffab40{% else %}#5a5880{% endif %}">{{ row.mismatches }}</td>
        <td style="display:flex;gap:6px">
          <form method="POST" action="/dashboard/admin/revoke">
            <input type="hidden" name="key" value="{{ row.raw }}">
            <button class="btn btn-sm btn-red" type="submit" {% if row.revoked %}disabled{% endif %}>Revoke</button>
          </form>
          <form method="POST" action="/dashboard/admin/reset-hwid">
            <input type="hidden" name="key" value="{{ row.raw }}">
            <button class="btn btn-sm btn-blue" type="submit">Reset HWID</button>
          </form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
"""

@flask_app.route("/verify", methods=["POST"])
def verify():
    data        = request.get_json(silent=True) or {}
    secret      = str(data.get("secret",      "")).strip()
    user_id     = str(data.get("user_id",     "")).strip()
    license_key = str(data.get("license_key", "")).strip()
    hwid        = str(data.get("hwid",        "")).strip()

    # Shared secret check — stops random people hitting your endpoint
    if secret != SECRET_KEY:
        return jsonify({"valid": False, "message": "Unauthorized."}), 401

    if not user_id or not license_key or not hwid:
        return jsonify({"valid": False, "message": "Missing fields."})

    key = normalise_key(license_key)
    hwid_hash = hashlib.sha256(hwid.encode()).hexdigest()

    with _db_lock:
        db = load_db()

        if key not in db:
            return jsonify({"valid": False,
                            "message": "Invalid license key. Use /redeem in our Discord."})

        entry = db[key]

        if entry.get("revoked"):
            return jsonify({"valid": False,
                            "message": "License revoked. Contact support."})

        # Discord ID check
        if entry.get("discord_id") and entry["discord_id"] != user_id:
            return jsonify({"valid": False,
                            "message": "Key registered to a different Discord account."})

        # HWID binding
        if not entry.get("hwid_hash"):
            # First activation — bind
            entry["hwid_hash"]        = hwid_hash
            entry["discord_id"]       = user_id
            entry["activated_at"]     = datetime.now(timezone.utc).isoformat()
            entry["activation_count"] = entry.get("activation_count", 0) + 1
            db[key] = entry
            save_db(db)
            return jsonify({"valid": True,
                            "message": "License activated! Welcome."})

        if entry["hwid_hash"] != hwid_hash:
            entry["mismatch_count"] = entry.get("mismatch_count", 0) + 1
            entry["last_mismatch"]  = datetime.now(timezone.utc).isoformat()
            db[key] = entry
            save_db(db)
            return jsonify({"valid": False,
                            "message": "Hardware mismatch. Key bound to another machine. "
                                       "DM an admin to transfer your license."})

        # All good
        entry["last_seen"] = datetime.now(timezone.utc).isoformat()
        db[key] = entry
        save_db(db)
        return jsonify({"valid": True, "message": "Authenticated."})


@flask_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ─────────────────────────────────────────────────────────────
#  DASHBOARD ROUTES
# ─────────────────────────────────────────────────────────────

@flask_app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect("/dashboard/login")
    if session.get("is_admin"):
        return redirect("/dashboard/admin")

    username = session.get("username")
    with _db_lock:
        db = load_db()

    # Find key for this user
    entry = None
    raw_key = None
    for k, v in db.items():
        if v.get("username") == username:
            entry = v
            raw_key = k
            break

    if not entry:
        return redirect("/dashboard/logout")

    display = "-".join(raw_key[i:i+4] for i in range(0, len(raw_key), 4))
    return render_template_string(DASHBOARD_TEMPLATE,
        key=display,
        revoked=entry.get("revoked", False),
        activated=entry.get("activated_at") is not None,
        hwid_bound=bool(entry.get("hwid_hash")),
        activated_at=(entry.get("activated_at") or "")[:19],
        last_seen=(entry.get("last_seen") or "")[:19],
    )


@flask_app.route("/dashboard/login", methods=["GET", "POST"])
def dashboard_login():
    if request.method == "GET":
        return render_template_string(LOGIN_TEMPLATE, error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    # Admin login
    if username == "admin" and password == ADMIN_PASSWORD:
        session["logged_in"] = True
        session["is_admin"]  = True
        session["username"]  = "admin"
        return redirect("/dashboard/admin")

    # Buyer login — check username+password in db
    with _db_lock:
        db = load_db()

    for k, v in db.items():
        if (v.get("username") == username and
                v.get("portal_password") == hashlib.sha256(password.encode()).hexdigest()):
            if v.get("revoked"):
                return render_template_string(LOGIN_TEMPLATE,
                    error="Your license has been revoked. Contact support.")
            session["logged_in"] = True
            session["is_admin"]  = False
            session["username"]  = username
            return redirect("/dashboard")

    return render_template_string(LOGIN_TEMPLATE, error="Invalid username or password.")


@flask_app.route("/dashboard/logout")
def dashboard_logout():
    session.clear()
    return redirect("/dashboard/login")


@flask_app.route("/dashboard/admin")
def dashboard_admin():
    if not session.get("is_admin"):
        return redirect("/dashboard/login")
    with _db_lock:
        db = load_db()

    keys = []
    for raw_key, entry in db.items():
        display = "-".join(raw_key[i:i+4] for i in range(0, len(raw_key), 4))
        keys.append({
            "raw":       raw_key,
            "display":   display,
            "username":  entry.get("username") or "—",
            "revoked":   entry.get("revoked", False),
            "activated": entry.get("activated_at") is not None,
            "hwid_bound": bool(entry.get("hwid_hash")),
            "mismatches": entry.get("mismatch_count", 0),
        })

    return render_template_string(ADMIN_TEMPLATE,
        keys=keys, msg=None, msg_type=None, new_key=None)


@flask_app.route("/dashboard/admin/add", methods=["POST"])
def dashboard_admin_add():
    if not session.get("is_admin"):
        return redirect("/dashboard/login")

    discord_id = request.form.get("discord_id", "").strip()
    username   = request.form.get("username",   "").strip()
    password   = request.form.get("password",   "").strip()

    if not username or not password:
        return redirect("/dashboard/admin")

    with _db_lock:
        db = load_db()

        # Check username not taken
        for v in db.values():
            if v.get("username") == username:
                return _admin_page(db, msg="Username already exists.", msg_type="error")

        raw_key = normalise_key(generate_key())
        db[raw_key] = {
            "discord_id":       discord_id or None,
            "username":         username,
            "portal_password":  hashlib.sha256(password.encode()).hexdigest(),
            "hwid_hash":        None,
            "revoked":          False,
            "created_at":       datetime.now(timezone.utc).isoformat(),
            "activated_at":     None,
            "last_seen":        None,
            "activation_count": 0,
            "mismatch_count":   0,
        }
        save_db(db)

    display = "-".join(raw_key[i:i+4] for i in range(0, len(raw_key), 4))
    return _admin_page(db,
        msg=f"Key created for {username}: {display}",
        msg_type="success",
        new_key=display)


@flask_app.route("/dashboard/admin/revoke", methods=["POST"])
def dashboard_admin_revoke():
    if not session.get("is_admin"):
        return redirect("/dashboard/login")
    key = normalise_key(request.form.get("key", ""))
    with _db_lock:
        db = load_db()
        if key in db:
            db[key]["revoked"]    = True
            db[key]["revoked_at"] = datetime.now(timezone.utc).isoformat()
            save_db(db)
    return _admin_page(db, msg="Key revoked.", msg_type="success")


@flask_app.route("/dashboard/admin/reset-hwid", methods=["POST"])
def dashboard_admin_reset_hwid():
    if not session.get("is_admin"):
        return redirect("/dashboard/login")
    key = normalise_key(request.form.get("key", ""))
    with _db_lock:
        db = load_db()
        if key in db:
            db[key]["hwid_hash"]     = None
            db[key]["hwid_reset_at"] = datetime.now(timezone.utc).isoformat()
            save_db(db)
    return _admin_page(db, msg="HWID reset. Next launch binds new machine.", msg_type="success")


def _admin_page(db, msg=None, msg_type=None, new_key=None):
    keys = []
    for raw_key, entry in db.items():
        display = "-".join(raw_key[i:i+4] for i in range(0, len(raw_key), 4))
        keys.append({
            "raw":        raw_key,
            "display":    display,
            "username":   entry.get("username") or "—",
            "revoked":    entry.get("revoked", False),
            "activated":  entry.get("activated_at") is not None,
            "hwid_bound": bool(entry.get("hwid_hash")),
            "mismatches": entry.get("mismatch_count", 0),
        })
    return render_template_string(ADMIN_TEMPLATE,
        keys=keys, msg=msg, msg_type=msg_type, new_key=new_key)

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, debug=False)

# ─────────────────────────────────────────────────────────────
#  DISCORD BOT
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False
    role = interaction.guild.get_role(ADMIN_ROLE_ID)
    if role is None:
        # Fallback: server owner or administrator permission
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)
    return role in interaction.user.roles


# ── /addkey ─────────────────────────────────────────────────
@tree.command(name="addkey", description="Generate a license key for a buyer")
@app_commands.describe(
    discord_id="Buyer's Discord user ID (18-digit number)",
    custom_key="Optional custom key (leave blank to auto-generate)"
)
async def addkey(interaction: discord.Interaction,
                 discord_id: str,
                 custom_key: str = ""):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    with _db_lock:
        db = load_db()
        if custom_key:
            key_raw = normalise_key(custom_key)
        else:
            key_raw = normalise_key(generate_key())

        if key_raw in db:
            await interaction.followup.send(
                f"⚠️ Key already exists: `{'-'.join(key_raw[i:i+4] for i in range(0,len(key_raw),4))}`",
                ephemeral=True)
            return

        db[key_raw] = {
            "discord_id":       discord_id.strip() or None,
            "hwid_hash":        None,
            "revoked":          False,
            "created_at":       datetime.now(timezone.utc).isoformat(),
            "activated_at":     None,
            "last_seen":        None,
            "activation_count": 0,
            "mismatch_count":   0,
        }
        save_db(db)

    display = "-".join(key_raw[i:i+4] for i in range(0, len(key_raw), 4))

    embed = discord.Embed(
        title="✅ License Key Generated",
        color=0x9b59b6
    )
    embed.add_field(name="Key",        value=f"`{display}`",   inline=False)
    embed.add_field(name="Discord ID", value=discord_id or "Not bound", inline=True)
    embed.add_field(name="Status",     value="Unactivated",    inline=True)
    embed.set_footer(text="Send this key to the buyer via DM")

    await interaction.followup.send(embed=embed, ephemeral=True)

    # Try to DM the buyer
    if discord_id.isdigit():
        try:
            user = await bot.fetch_user(int(discord_id))
            dm_embed = discord.Embed(
                title="🔑 Your License Key",
                description=f"Here is your license key for the Token Generator.",
                color=0x9b59b6
            )
            dm_embed.add_field(name="License Key", value=f"`{display}`", inline=False)
            dm_embed.add_field(
                name="How to activate",
                value="1. Launch the tool\n2. Enter your Discord ID\n3. Enter the key above",
                inline=False
            )
            dm_embed.set_footer(text="This key is bound to your hardware on first use.")
            await user.send(embed=dm_embed)
        except Exception:
            pass  # User has DMs closed — that's fine


# ── /revoke ──────────────────────────────────────────────────
@tree.command(name="revoke", description="Revoke a license key immediately")
@app_commands.describe(key="The license key to revoke (e.g. ABCD-1234-EFGH-5678)")
async def revoke(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "❌ No permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    key_raw = normalise_key(key)

    with _db_lock:
        db = load_db()
        if key_raw not in db:
            await interaction.followup.send("❌ Key not found.", ephemeral=True)
            return
        db[key_raw]["revoked"]    = True
        db[key_raw]["revoked_at"] = datetime.now(timezone.utc).isoformat()
        save_db(db)

    display = "-".join(key_raw[i:i+4] for i in range(0, len(key_raw), 4))
    await interaction.followup.send(
        f"🚫 Key `{display}` has been **revoked**. Tool will block on next launch.",
        ephemeral=True)


# ── /resethwid ───────────────────────────────────────────────
@tree.command(name="resethwid", description="Reset HWID binding (buyer got new PC)")
@app_commands.describe(key="The license key to reset")
async def resethwid(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "❌ No permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    key_raw = normalise_key(key)

    with _db_lock:
        db = load_db()
        if key_raw not in db:
            await interaction.followup.send("❌ Key not found.", ephemeral=True)
            return
        db[key_raw]["hwid_hash"]     = None
        db[key_raw]["hwid_reset_at"] = datetime.now(timezone.utc).isoformat()
        save_db(db)

    display = "-".join(key_raw[i:i+4] for i in range(0, len(key_raw), 4))
    await interaction.followup.send(
        f"✅ HWID reset for `{display}`. Next launch will bind to the new machine.",
        ephemeral=True)


# ── /listkeys ────────────────────────────────────────────────
@tree.command(name="listkeys", description="List all license keys and their status")
async def listkeys(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "❌ No permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    with _db_lock:
        db = load_db()

    if not db:
        await interaction.followup.send("No keys in database.", ephemeral=True)
        return

    lines = []
    for raw_key, entry in list(db.items())[:25]:  # Discord 2000 char limit
        display  = "-".join(raw_key[i:i+4] for i in range(0, len(raw_key), 4))
        status   = "🚫 Revoked" if entry.get("revoked") else (
                   "✅ Active"  if entry.get("activated_at") else "⏳ Unused")
        discord_id = entry.get("discord_id") or "—"
        mismatches = entry.get("mismatch_count", 0)
        mismatch_str = f" ⚠️ {mismatches} HWID mismatches" if mismatches > 0 else ""
        lines.append(f"`{display}` | {status} | <@{discord_id}>{mismatch_str}")

    embed = discord.Embed(
        title=f"License Keys ({len(db)} total)",
        description="\n".join(lines),
        color=0x9b59b6
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


# ── /checkkey ────────────────────────────────────────────────
@tree.command(name="checkkey", description="Check details of a specific key")
@app_commands.describe(key="The license key to check")
async def checkkey(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ No permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    key_raw = normalise_key(key)

    with _db_lock:
        db = load_db()
        if key_raw not in db:
            await interaction.followup.send("❌ Key not found.", ephemeral=True)
            return
        entry = db[key_raw]

    display = "-".join(key_raw[i:i+4] for i in range(0, len(key_raw), 4))

    embed = discord.Embed(
        title=f"Key: {display}",
        color=0xe74c3c if entry.get("revoked") else 0x2ecc71
    )
    embed.add_field(name="Status",
                    value="🚫 Revoked" if entry.get("revoked") else
                          ("✅ Active" if entry.get("activated_at") else "⏳ Unused"),
                    inline=True)
    embed.add_field(name="Discord",
                    value=f"<@{entry['discord_id']}>" if entry.get("discord_id") else "—",
                    inline=True)
    embed.add_field(name="HWID Bound",   value="Yes" if entry.get("hwid_hash") else "No", inline=True)
    embed.add_field(name="Activated",    value=entry.get("activated_at",  "Never")[:19], inline=True)
    embed.add_field(name="Last Seen",    value=entry.get("last_seen",     "Never")[:19], inline=True)
    embed.add_field(name="Mismatches",   value=str(entry.get("mismatch_count", 0)),      inline=True)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ── Bot ready ────────────────────────────────────────────────
@bot.event
async def on_ready():
    await tree.sync()
    print(f"Bot online: {bot.user}")
    print(f"HTTP server running on port {PORT}")


# ─────────────────────────────────────────────────────────────
#  ENTRY — run Flask in a thread, Discord bot in main thread
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("No DISCORD_TOKEN set — running HTTP server only")
        flask_thread.join()
