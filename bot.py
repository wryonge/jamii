import logging
from datetime import datetime, timedelta
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # type: ignore
from telegram.ext import ( # type: ignore
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for the conversation
(
    CHOOSING_PACKAGE,
    SELECTING_QUANTITY,
    PAYMENT_PROCESS,
    WAITING_CONFIRMATION,
    ADMIN_REVIEW,
) = range(5)

# Data for bundles
BUNDLES = {
    "3hr": {"duration": "3 hours", "price": 80},
    "24hr": {"duration": "24 hours", "price": 200},
}

# Bot status
BOT_STATUS = {
    "online": True,
    "offline_message": "Sorry, the service is currently offline. We'll notify you when we're back online.",
}

# Store for pending orders and users who tried when offline
PENDING_ORDERS = {}
OFFLINE_USERS = set()

# File paths for persistence
DATA_DIR = "data"
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")
OFFLINE_USERS_FILE = os.path.join(DATA_DIR, "offline_users.json")
BOT_STATUS_FILE = os.path.join(DATA_DIR, "bot_status.json")

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

# Admin user IDs - replace with actual admin IDs
ADMIN_IDS = [5796266950]  # Add your Telegram user ID here

def load_data_from_disk():
    """Load saved data from disk"""
    global PENDING_ORDERS, OFFLINE_USERS, BOT_STATUS
    
    # Load pending orders
    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, 'r') as f:
            PENDING_ORDERS = json.load(f)
    
    # Load offline users
    if os.path.exists(OFFLINE_USERS_FILE):
        with open(OFFLINE_USERS_FILE, 'r') as f:
            OFFLINE_USERS = set(json.load(f))
    
    # Load bot status
    if os.path.exists(BOT_STATUS_FILE):
        with open(BOT_STATUS_FILE, 'r') as f:
            BOT_STATUS = json.load(f)

def save_data_to_disk():
    """Save data to disk"""
    # Save pending orders
    with open(ORDERS_FILE, 'w') as f:
        json.dump(PENDING_ORDERS, f)
    
    # Save offline users
    with open(OFFLINE_USERS_FILE, 'w') as f:
        json.dump(list(OFFLINE_USERS), f)
    
    # Save bot status
    with open(BOT_STATUS_FILE, 'w') as f:
        json.dump(BOT_STATUS, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    
    if not BOT_STATUS["online"]:
        OFFLINE_USERS.add(user.id)
        save_data_to_disk()
        await update.message.reply_text(BOT_STATUS["offline_message"])
        return ConversationHandler.END
    
    await update.message.reply_text(
        f"Hello {user.first_name}! Welcome to the Data Bundle Bot.\n\n"
        "You can buy the following packages:\n"
        "1. 3 hours - KSh 80\n"
        "2. 24 hours - KSh 200\n\n"
        "Please select a package to continue.",
        reply_markup=get_package_keyboard()
    )
    
    return CHOOSING_PACKAGE

def get_package_keyboard():
    """Create keyboard with bundle options"""
    keyboard = [
        [
            InlineKeyboardButton("3 hours - KSh 80", callback_data="package_3hr"),
            InlineKeyboardButton("24 hours - KSh 200", callback_data="package_24hr"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def package_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle package selection"""
    query = update.callback_query
    await query.answer()
    
    # Extract package type from callback data
    package_type = query.data.split("_")[1]
    context.user_data["package_type"] = package_type
    
    # Ask for quantity
    await query.edit_message_text(
        f"You selected the {BUNDLES[package_type]['duration']} package at KSh {BUNDLES[package_type]['price']}.\n\n"
        "How many packages would you like to buy? (Send a number)"
    )
    
    return SELECTING_QUANTITY

async def quantity_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle quantity selection"""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("Please enter a positive number.")
            return SELECTING_QUANTITY
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return SELECTING_QUANTITY
    
    package_type = context.user_data["package_type"]
    price_per_unit = BUNDLES[package_type]["price"]
    total_price = price_per_unit * quantity
    
    context.user_data["quantity"] = quantity
    context.user_data["total_price"] = total_price
    
    # Payment instructions
    await update.message.reply_text(
        f"You're purchasing {quantity} x {BUNDLES[package_type]['duration']} data bundle(s).\n"
        f"Total amount: KSh {total_price}\n\n"
        "Please pay via M-PESA:\n"
        "1. Go to M-PESA menu\n"
        "2. Select Pay Bill\n"
        "3. Enter Business No: 123456\n"
        "4. Enter Account No: DATA\n"
        f"5. Enter Amount: {total_price}\n"
        "6. Enter your M-PESA PIN and confirm\n\n"
        "After payment, please send your transaction ID."
    )
    
    return PAYMENT_PROCESS

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle payment transaction ID submission"""
    transaction_id = update.message.text.strip()
    
    if not transaction_id:
        await update.message.reply_text("Please provide a valid transaction ID.")
        return PAYMENT_PROCESS
    
    # Store order details
    user = update.effective_user
    package_type = context.user_data["package_type"]
    quantity = context.user_data["quantity"]
    total_price = context.user_data["total_price"]
    
    order_id = f"ORDER_{user.id}_{int(datetime.now().timestamp())}"
    
    order_details = {
        "order_id": order_id,
        "user_id": user.id,
        "user_name": user.first_name,
        "username": user.username,
        "package_type": package_type,
        "quantity": quantity,
        "total_price": total_price,
        "transaction_id": transaction_id,
        "status": "pending",
        "timestamp": datetime.now().isoformat(),
    }
    
    PENDING_ORDERS[order_id] = order_details
    save_data_to_disk()
    
    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            keyboard = [
                [
                    InlineKeyboardButton("Approve", callback_data=f"approve_{order_id}"),
                    InlineKeyboardButton("Reject", callback_data=f"reject_{order_id}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            admin_msg = (
                f"🔔 NEW ORDER: {order_id}\n\n"
                f"User: {user.first_name} (@{user.username})\n"
                f"Package: {BUNDLES[package_type]['duration']}\n"
                f"Quantity: {quantity}\n"
                f"Total: KSh {total_price}\n"
                f"Transaction ID: {transaction_id}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_msg,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    # Inform user
    await update.message.reply_text(
        f"Thank you! Your order (ID: {order_id}) has been submitted for review.\n"
        "We'll process it shortly and notify you once it's approved."
    )
    
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin approval or rejection"""
    query = update.callback_query
    await query.answer()
    
    action, order_id = query.data.split("_", 1)
    
    if order_id not in PENDING_ORDERS:
        await query.edit_message_text("Order not found or already processed.")
        return
    
    order = PENDING_ORDERS[order_id]
    user_id = order["user_id"]
    
    if action == "approve":
        # Update order status
        PENDING_ORDERS[order_id]["status"] = "approved"
        PENDING_ORDERS[order_id]["approved_at"] = datetime.now().isoformat()
        PENDING_ORDERS[order_id]["approved_by"] = update.effective_user.id
        save_data_to_disk()
        
        # Calculate expiry time
        package_type = order["package_type"]
        quantity = order["quantity"]
        
        if package_type == "3hr":
            hours = 3 * quantity
        else:  # 24hr
            hours = 24 * quantity
            
        expiry_time = datetime.now() + timedelta(hours=hours)
        expiry_str = expiry_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 Good news! Your order (ID: {order_id}) has been approved.\n\n"
                     f"Your data bundle is now active and will expire on {expiry_str}.\n\n"
                     f"Enjoy your {hours} hours of internet!"
            )
            
            await query.edit_message_text(
                f"✅ Order {order_id} has been approved and activated.\n"
                f"User has been notified."
            )
        except Exception as e:
            await query.edit_message_text(
                f"✅ Order approved but failed to notify user: {e}"
            )
    
    elif action == "reject":
        # Update order status
        PENDING_ORDERS[order_id]["status"] = "rejected"
        PENDING_ORDERS[order_id]["rejected_at"] = datetime.now().isoformat()
        PENDING_ORDERS[order_id]["rejected_by"] = update.effective_user.id
        save_data_to_disk()
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Unfortunately, your order (ID: {order_id}) has been rejected.\n\n"
                     "This may be due to payment verification issues. Please contact support for assistance."
            )
            
            await query.edit_message_text(
                f"❌ Order {order_id} has been rejected.\n"
                f"User has been notified."
            )
        except Exception as e:
            await query.edit_message_text(
                f"❌ Order rejected but failed to notify user: {e}"
            )

async def admin_toggle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle bot online/offline status (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("You are not authorized to use this command.")
        return
    
    # Toggle status
    BOT_STATUS["online"] = not BOT_STATUS["online"]
    status = "ONLINE" if BOT_STATUS["online"] else "OFFLINE"
    
    # If going back online, notify users who tried when offline
    if BOT_STATUS["online"] and OFFLINE_USERS:
        for user_id in OFFLINE_USERS:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🟢 We're back online! You can now purchase data bundles."
                )
            except Exception as e:
                logger.error(f"Failed to notify offline user {user_id}: {e}")
        
        await update.message.reply_text(
            f"Bot is now {status}. Notified {len(OFFLINE_USERS)} users who tried when offline."
        )
        OFFLINE_USERS.clear()
    else:
        await update.message.reply_text(f"Bot is now {status}.")
    
    save_data_to_disk()

async def admin_set_offline_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set custom offline message (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("You are not authorized to use this command.")
        return
    
    # Get message from command arguments
    if not context.args:
        await update.message.reply_text(
            "Please provide an offline message. Usage: /setofflinemsg Your custom message here"
        )
        return
    
    offline_message = " ".join(context.args)
    BOT_STATUS["offline_message"] = offline_message
    save_data_to_disk()
    
    await update.message.reply_text(f"Offline message updated successfully:\n\n{offline_message}")

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin help"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        # Regular user help
        await update.message.reply_text(
            "Available commands:\n"
            "/start - Start shopping for data bundles\n"
            "/help - Show this help message"
        )
        return
    
    # Admin help
    await update.message.reply_text(
        "Admin Commands:\n"
        "/togglestatus - Toggle bot online/offline status\n"
        "/setofflinemsg [message] - Set custom offline message\n"
        "/pendingorders - View all pending orders\n"
        "/help - Show this help message"
    )

async def admin_view_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View pending orders (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("You are not authorized to use this command.")
        return
    
    pending = {k: v for k, v in PENDING_ORDERS.items() if v["status"] == "pending"}
    
    if not pending:
        await update.message.reply_text("No pending orders.")
        return
    
    for order_id, order in pending.items():
        keyboard = [
            [
                InlineKeyboardButton("Approve", callback_data=f"approve_{order_id}"),
                InlineKeyboardButton("Reject", callback_data=f"reject_{order_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        package_type = order["package_type"]
        
        admin_msg = (
            f"🔔 PENDING ORDER: {order_id}\n\n"
            f"User: {order['user_name']} (@{order.get('username', 'N/A')})\n"
            f"Package: {BUNDLES[package_type]['duration']}\n"
            f"Quantity: {order['quantity']}\n"
            f"Total: KSh {order['total_price']}\n"
            f"Transaction ID: {order['transaction_id']}\n"
            f"Time: {order['timestamp']}"
        )
        
        await update.message.reply_text(
            text=admin_msg,
            reply_markup=reply_markup
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current operation"""
    await update.message.reply_text("Operation cancelled. Type /start to begin again.")
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    # Load saved data
    load_data_from_disk()
    
    # Create the Application
    application = Application.builder().token("7963857754:AAEUoZvj8CRtgTBlBFnwLyCioIIVNhxJ6kY").build()

    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_PACKAGE: [
                CallbackQueryHandler(package_choice, pattern=r"^package_")
            ],
            SELECTING_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_selection)
            ],
            PAYMENT_PROCESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    
    # Add admin command handlers
    application.add_handler(CommandHandler("togglestatus", admin_toggle_status))
    application.add_handler(CommandHandler("setofflinemsg", admin_set_offline_message))
    application.add_handler(CommandHandler("pendingorders", admin_view_pending))
    application.add_handler(CommandHandler("help", admin_help))
    
    # Add callback query handler for admin actions
    application.add_handler(CallbackQueryHandler(admin_action, pattern=r"^(approve|reject)_"))

    
import os
import traceback
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

async def start(update, context):
    await update.message.reply_text("Hello! I'm running.")

async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    print("Exception while handling an update:")
    traceback.print_exception(
        type(context.error),
        context.error,
        context.error.__traceback__
    )

def main():
    token = os.getenv("BOT_TOKEN")
    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_error_handler(error_handler)  # ✅ REGISTER ERROR HANDLER

    application.run_polling()

if __name__ == "__main__":
    main()

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == "__main__":
    main()