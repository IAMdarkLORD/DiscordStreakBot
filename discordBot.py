import os
import discord
import logging
import sqlite3
import shutil
import time
import openai
import matplotlib.pyplot as plt
from discord.ext import commands, tasks
from dotenv import load_dotenv
import calendar

# Setup logging
logging.basicConfig(filename="bot.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables from .env file
load_dotenv()

# Connect to SQLite database
DB_FILE = "progress.db"
BACKUP_FOLDER = "backups"
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# Create table if not exists
cursor.execute("""CREATE TABLE IF NOT EXISTS progress (
    user_id INT, activity TEXT, count INT, date TEXT)""")
conn.commit()

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Load API keys from environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
print("Printing ----> ",DISCORD_TOKEN)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY


# 🛠 Logging function
def log_message(message):
    logging.info(message)


# 📥 Log user activity
@bot.command()
async def log(ctx, activity: str, count: int):
    user_id = ctx.author.id
    cursor.execute("INSERT INTO progress VALUES (?, ?, ?, DATE('now'))", (user_id, activity, count))
    conn.commit()

    streak = get_user_streak(user_id)
    log_message(f"{ctx.author.name} logged {count} {activity}. Streak: {streak} days")

    await ctx.send(f"✅ {ctx.author.name}, you logged {count} {activity}! 🔥 Streak: {streak} days")


# 🔥 Get user streak
def get_user_streak(user_id):
    cursor.execute(
        """SELECT COUNT(DISTINCT date) FROM progress 
           WHERE user_id=? AND date >= DATE('now', '-7 days')""",
        (user_id,),
    )
    streak = cursor.fetchone()[0]
    return streak


# 📊 Generate weekly progress chart
def generate_chart(user_id):
    cursor.execute("SELECT activity, SUM(count) FROM progress WHERE user_id=? AND date >= DATE('now', '-7 days') GROUP BY activity", (user_id,))
    data = cursor.fetchall()

    if not data:
        return None

    activities, counts = zip(*data)
    plt.figure(figsize=(6, 4))
    plt.bar(activities, counts, color="skyblue")
    plt.xlabel("Activity")
    plt.ylabel("Count")
    plt.title("Weekly Progress")
    chart_path = "weekly_summary.png"
    plt.savefig(chart_path)
    return chart_path


@bot.command()
async def weekly_summary(ctx):
    user_id = ctx.author.id
    chart_path = generate_chart(user_id)
    if chart_path:
        await ctx.send(file=discord.File(chart_path))
    else:
        await ctx.send("No data logged this week.")


# 🤖 AI-powered progress analysis
def analyze_progress(user_id):
    cursor.execute("SELECT activity, SUM(count) FROM progress WHERE user_id=? AND date >= DATE('now', '-14 days') GROUP BY activity", (user_id,))
    last_2_weeks = cursor.fetchall()

    if not last_2_weeks:
        return "No data available for analysis."

    prompt = f"Here is the weekly data for user {user_id}: {last_2_weeks}. Analyze the progress, identify weak points, and suggest improvements."

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a fitness and productivity coach."},
            {"role": "user", "content": prompt},
        ],
    )

    return response["choices"][0]["message"]["content"]


@bot.command()
async def analyze(ctx):
    user_id = ctx.author.id
    insights = analyze_progress(user_id)
    await ctx.send(insights)


# 🏆 Leaderboard
@bot.command()
async def leaderboard(ctx):
    cursor.execute("""SELECT user_id, SUM(count) FROM progress WHERE date >= DATE('now', '-7 days') 
                      GROUP BY user_id ORDER BY SUM(count) DESC LIMIT 5""")
    top_users = cursor.fetchall()

    if not top_users:
        await ctx.send("No data available for the leaderboard!")
        return

    leaderboard_text = "**🏆 Weekly Leaderboard 🏆**\n"
    for rank, (user_id, total) in enumerate(top_users, start=1):
        user = await bot.fetch_user(user_id)
        leaderboard_text += f"**{rank}. {user.name}** - {total} points\n"

    await ctx.send(leaderboard_text)


@bot.command()
async def smart_log(ctx, *, message: str):
    """
    Logs user activities from natural language.
    Example: "/smart_log I ran 5km and solved 3 coding problems"
    """
    user_id = ctx.author.id

    prompt = f"""
    Extract and structure this log entry: "{message}". 
    Identify the activity, count, and unit. If it's new, create a relevant category.
    Return the result in JSON format like this:
    [
        {{"activity": "running", "count": 5, "unit": "km"}},
        {{"activity": "coding", "count": 3, "unit": "problems"}}
    ]
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        activities = eval(response["choices"][0]["message"]["content"])  # Convert JSON-like response to Python list
    except Exception as e:
        await ctx.send("❌ Could not process your log. Try rephrasing it!")
        return

    logged_activities = []
    
    for entry in activities:
        activity = entry["activity"].lower()
        count = int(entry["count"])
        cursor.execute("INSERT INTO progress VALUES (?, ?, ?, DATE('now'))", (user_id, activity, count))
        conn.commit()
        logged_activities.append(f"✅ {count} {entry['unit']} of {activity} logged!")

    if logged_activities:
        await ctx.send("\n".join(logged_activities))
    else:
        await ctx.send("❌ Could not detect any activities.")






@bot.command()
async def calendar(ctx, month: int = None, year: int = None):
    """Generates a calendar heatmap of activity logs for a given month."""
    user_id = ctx.author.id

    if month is None or year is None:
        today = time.localtime()
        year, month = today.tm_year, today.tm_mon

    cursor.execute("""
        SELECT DISTINCT date FROM progress 
        WHERE user_id=? AND strftime('%Y-%m', date) = ?
    """, (user_id, f"{year}-{month:02}"))
    
    activity_days = {row[0] for row in cursor.fetchall()}

    # Generate calendar
    cal = calendar.monthcalendar(year, month)
    plt.figure(figsize=(6, 4))

    for week_idx, week in enumerate(cal):
        for day_idx, day in enumerate(week):
            if day == 0:
                continue  # Skip empty days
            color = "green" if f"{year}-{month:02}-{day:02}" in activity_days else "red"
            plt.text(day_idx, -week_idx, str(day), color=color, fontsize=12, ha="center")

    plt.xticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    plt.yticks([])
    plt.title(f"Activity Calendar for {calendar.month_name[month]} {year}")

    chart_path = "activity_calendar.png"
    plt.savefig(chart_path)
    await ctx.send(file=discord.File(chart_path))


# ⏰ Check inactive users and remind them
@tasks.loop(hours=24)
async def check_inactive_users():
    cursor.execute("SELECT DISTINCT user_id FROM progress WHERE date >= DATE('now', '-3 days')")
    active_users = {row[0] for row in cursor.fetchall()}

    for guild in bot.guilds:
        for member in guild.members:
            if member.id not in active_users and not member.bot:
                await member.send("Hey! 👋 You haven’t logged activity in 3 days. Stay consistent!")
                log_message(f"Sent reminder to {member.name}")


# 📂 Automatic Database Backup
def backup_database():
    if not os.path.exists(BACKUP_FOLDER):
        os.makedirs(BACKUP_FOLDER)

    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = os.path.join(BACKUP_FOLDER, f"backup_{timestamp}.db")

    shutil.copy(DB_FILE, backup_path)
    log_message(f"Database backed up: {backup_path}")


@tasks.loop(hours=24)
async def daily_backup():
    backup_database()


@bot.event
async def on_ready():
    print(f"Bot {bot.user} is online!")
    check_inactive_users.start()
    daily_backup.start()


response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hi"}],
    )

print(response.choices[0].message.content)


# Run the bot
bot.run(DISCORD_TOKEN)

# MTM0MzUzMTY1MzY4MjgyMzIwOQ.G4204u.klOWGOoJptnKz1aMYBIrI26Mv3TYso1MuDZTpY