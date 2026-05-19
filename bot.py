import logging
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
from config import config
from database import Database, UserState
from ai_architect import AIArchitect
from github_manager import GitHubManager
from smart_features import SmartProjectDetector

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

class ProjectCreatorBot:
    def __init__(self):
        self.db = Database(config.DATABASE_PATH)
        self.ai = AIArchitect()
        self.github = GitHubManager()
        self.user_projects_today = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.get_or_create_user(user.id, user.username, user.first_name, user.last_name)
        self.db.update_user_state(user.id, UserState.WAITING_PROJECT_PROMPT)
        await update.message.reply_text(
            f"🚀 Welcome {user.first_name}!\n\nSend me your project idea (e.g., 'Create a simple calculator in Python').\n\n"
            f"💡 You can also say: 'Modify my last project – add a new function X'.\n"
            f"🛑 /stop to cancel generation.\n"
            f"✅ Only /start and /stop are commands; rest is natural conversation.",
            parse_mode=ParseMode.MARKDOWN
        )

    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        session = self.db.get_active_session(user_id)
        if session:
            self.db.update_project_session(session['id'], status='cancelled')
        self.db.update_user_state(user_id, UserState.IDLE)
        await update.message.reply_text("🛑 Generation stopped. Use /start to begin new project.", parse_mode=ParseMode.MARKDOWN)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id
        text = update.message.text.strip()
        state = self.db.get_user_state(user_id)
        self.db.add_conversation_message(user_id, "user", text)

        # Check for modify intent
        if "modify" in text.lower() or "change" in text.lower() or "update" in text.lower():
            last_blueprint = self.db.get_last_project_blueprint(user_id)
            if last_blueprint:
                await self._handle_modify(update, context, user_id, text, last_blueprint)
                return
            else:
                await update.message.reply_text("No previous project found. Please send a new project idea.", parse_mode=ParseMode.MARKDOWN)
                return

        # Normal flow
        if state in [UserState.WAITING_PROJECT_PROMPT, UserState.IDLE]:
            await self._handle_new_project(update, context, user_id, text)
        elif state == UserState.WAITING_REPO_NAME:
            await self._handle_repo_name(update, context, user_id, text)
        elif state == UserState.WAITING_CONFIRMATION:
            await update.message.reply_text("Please use the buttons above.", parse_mode=ParseMode.MARKDOWN)
        elif state in [UserState.GENERATING_CODE, UserState.PUSHING_TO_GITHUB]:
            await update.message.reply_text("Generation in progress. Wait or type /stop to cancel.", parse_mode=ParseMode.MARKDOWN)

    async def _handle_new_project(self, update, context, user_id, prompt):
        # rate limit check
        today = datetime.now().date()
        if today not in self.user_projects_today:
            self.user_projects_today[today] = {}
        if self.user_projects_today[today].get(user_id, 0) >= config.MAX_PROJECTS_PER_HOUR:
            await update.message.reply_text("⏰ Rate limit reached. Try later.", parse_mode=ParseMode.MARKDOWN)
            return

        status_msg = await update.message.reply_text("🧠 Analyzing your idea...", parse_mode=ParseMode.MARKDOWN)
        try:
            blueprint = await self.ai.generate_blueprint(prompt)
            session_id = self.db.create_project_session(user_id, prompt)
            self.db.update_project_session(session_id, file_structure=json.dumps(blueprint))
            context.user_data['session_id'] = session_id
            context.user_data['blueprint'] = blueprint

            file_count = len(blueprint.get('file_structure', []))
            tech = ', '.join(blueprint.get('tech_stack', []))
            proj_name = blueprint.get('project_name', 'project')
            await status_msg.edit_text(
                f"✅ *Blueprint Ready*\n\n📁 Project: `{proj_name}`\n📄 Files: {file_count}\n🛠️ Tech: {tech}\n\n"
                f"📂 *Structure:*\n" + "\n".join(f"• `{f['path']}`" for f in blueprint['file_structure'][:10]) +
                (f"\n...and {file_count-10} more" if file_count>10 else "") +
                f"\n\n📁 *Enter GitHub repo name* (lowercase, hyphens only):",
                parse_mode=ParseMode.MARKDOWN
            )
            self.db.update_user_state(user_id, UserState.WAITING_REPO_NAME)
        except Exception as e:
            logger.error(f"Blueprint error: {e}")
            await status_msg.edit_text("❌ Failed to analyze. Please try again.", parse_mode=ParseMode.MARKDOWN)

    async def _handle_repo_name(self, update, context, user_id, repo_name):
        if not re.match(r'^[a-z0-9-]+$', repo_name):
            await update.message.reply_text("❌ Invalid. Only lowercase letters, numbers, hyphens.", parse_mode=ParseMode.MARKDOWN)
            return
        session_id = context.user_data.get('session_id')
        if session_id:
            self.db.update_project_session(session_id, repo_name=repo_name)
        blueprint = context.user_data.get('blueprint')
        if not blueprint:
            await update.message.reply_text("Session expired. Use /start again.", parse_mode=ParseMode.MARKDOWN)
            return
        size = SmartProjectDetector.detect_size(blueprint.get('description', ''))
        confirm_text = f"📋 *Ready to generate?*\n\nRepo: `{repo_name}`\nFiles: {len(blueprint['file_structure'])}\nEstimated time: 1-3 min.\n\nProceed?"
        keyboard = [[InlineKeyboardButton("✅ Create", callback_data="confirm_yes"), InlineKeyboardButton("❌ Cancel", callback_data="confirm_no")]]
        await update.message.reply_text(confirm_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        self.db.update_user_state(user_id, UserState.WAITING_CONFIRMATION)

    async def _handle_modify(self, update, context, user_id, modify_text, old_blueprint):
        status_msg = await update.message.reply_text("🔄 Analyzing modification request...", parse_mode=ParseMode.MARKDOWN)
        try:
            # ask AI to modify blueprint based on user's instruction
            sys_prompt = f"""You have an existing project blueprint: {json.dumps(old_blueprint)}.
User wants to modify it: "{modify_text}"
Return a new JSON blueprint with the modifications. Keep same tech stack, but add/change files as needed.
Do NOT add README.md.
Output exactly same JSON structure.
"""
            response = self.ai.client.chat.completions.create(
                model=config.DEEPSEEK_FLASH_MODEL,
                messages=[{"role": "system", "content": sys_prompt}],
                temperature=0.5,
                max_tokens=2000,
                response_format={"type": "json_object"}
            )
            new_blueprint = json.loads(response.choices[0].message.content)
            new_blueprint['file_structure'] = [f for f in new_blueprint.get('file_structure', []) if f['path'] != 'README.md']
            session_id = self.db.create_project_session(user_id, f"Modify: {modify_text}")
            self.db.update_project_session(session_id, file_structure=json.dumps(new_blueprint))
            context.user_data['session_id'] = session_id
            context.user_data['blueprint'] = new_blueprint
            file_count = len(new_blueprint.get('file_structure', []))
            await status_msg.edit_text(
                f"✅ *Modified Blueprint*\n\nFiles: {file_count}\n\n📁 Enter GitHub repo name (or same as before):",
                parse_mode=ParseMode.MARKDOWN
            )
            self.db.update_user_state(user_id, UserState.WAITING_REPO_NAME)
        except Exception as e:
            await status_msg.edit_text("❌ Modification failed. Try again with more details.", parse_mode=ParseMode.MARKDOWN)

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        if query.data == "confirm_yes":
            await self._generate_project(update, context, user_id)
        else:
            session_id = context.user_data.get('session_id')
            if session_id:
                self.db.update_project_session(session_id, status='cancelled')
            self.db.update_user_state(user_id, UserState.IDLE)
            await query.edit_message_text("❌ Cancelled. Use /start to begin new project.", parse_mode=ParseMode.MARKDOWN)

    async def _generate_project(self, update, context, user_id):
        query = update.callback_query
        progress_msg = await query.edit_message_text("🚀 Starting generation...\n[⬜⬜⬜⬜⬜] 0%", parse_mode=ParseMode.MARKDOWN)
        try:
            session_id = context.user_data.get('session_id')
            session = self.db.get_active_session(user_id)
            if not session:
                await progress_msg.edit_text("❌ Session expired. Use /start.", parse_mode=ParseMode.MARKDOWN)
                return
            blueprint = json.loads(session['file_structure'])
            repo_name = session['repo_name']
            self.db.update_user_state(user_id, UserState.GENERATING_CODE)

            async def progress_callback(msg):
                await progress_msg.edit_text(f"{msg}\n[🟦🟦🟦⬜⬜] 60%", parse_mode=ParseMode.MARKDOWN)

            await progress_msg.edit_text("🤖 Generating files...\n[🟦🟦🟦⬜⬜] 60%", parse_mode=ParseMode.MARKDOWN)
            files = await self.ai.generate_all_files(blueprint, progress_callback)

            await progress_msg.edit_text("🚀 Creating GitHub repo...\n[🟦🟦🟦🟦⬜] 80%", parse_mode=ParseMode.MARKDOWN)
            repo = await self.github.create_repo(repo_name, blueprint.get('description', ''))
            await progress_msg.edit_text(f"📤 Pushing {len(files)} files...\n[🟦🟦🟦🟦🟦] 95%", parse_mode=ParseMode.MARKDOWN)
            await self.github.push_files(repo, files)
            repo_url = self.github.get_repo_url(repo)
            self.db.update_project_session(session_id, github_url=repo_url, status='completed')
            # save to history
            self.db.add_to_history(user_id, session_id, blueprint.get('project_name', repo_name), blueprint, repo_url)

            # track usage
            today = datetime.now().date()
            if today not in self.user_projects_today:
                self.user_projects_today[today] = {}
            self.user_projects_today[today][user_id] = self.user_projects_today[today].get(user_id, 0) + 1

            await progress_msg.edit_text(
                f"✅ *Project Created!*\n\n📁 [{repo_name}]({repo_url})\n📊 {len(files)} files\n\n🔗 {repo_url}\n\n/start - New project",
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Generation error: {e}")
            await progress_msg.edit_text(f"❌ Error: {str(e)[:200]}\nTry again with /start", parse_mode=ParseMode.MARKDOWN)
        finally:
            self.db.update_user_state(user_id, UserState.IDLE)

    def run(self):
        app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("stop", self.stop))
        app.add_handler(CallbackQueryHandler(self.callback_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        print("✅ Bot is polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)