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
from flask import Flask, request, jsonify
import discord
from discord import app_commands
from discord.ext import commands

# ─────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────
DISCORD_TOKEN  = os.environ.get("DISCORD_TOKEN", "")
ADMIN_ROLE_ID  = int(os.environ.get("ADMIN_ROLE_ID", "0"))
SECRET_KEY     = os.environ.get("SECRET_KEY", "change_this_secret")
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
