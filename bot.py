import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, ADMIN_IDS
from database import init_db, get_session, User, Category, Product, Account, Purchase, Transaction
from sqlalchemy import select

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Admin States for adding content
class AddCategoryState(StatesGroup):
    waiting_for_name = State()

class AddProductState(StatesGroup):
    waiting_for_category = State()
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_stock = State()

class AddAccountState(StatesGroup):
    waiting_for_product = State()
    waiting_for_email = State()
    waiting_for_password = State()

class RechargeState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_screenshot = State()

# ========== USER COMMANDS ==========
@dp.message(Command("start"))
async def start_command(message: types.Message):
    async for session in get_session():
        # Check if user exists
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        
        if not user:
            new_user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                is_admin=message.from_user.id in ADMIN_IDS
            )
            session.add(new_user)
            await session.commit()
        
        # Main menu
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📂 Categories", callback_data="show_categories")],
            [InlineKeyboardButton(text="💰 My Wallet", callback_data="my_wallet")],
            [InlineKeyboardButton(text="📜 Purchase History", callback_data="purchase_history")],
            [InlineKeyboardButton(text="➕ Recharge Wallet", callback_data="recharge_wallet")]
        ])
        
        if message.from_user.id in ADMIN_IDS:
            keyboard.inline_keyboard.append([InlineKeyboardButton(text="⚙️ Admin Panel", callback_data="admin_panel")])
        
        await message.answer(
            f"Welcome {message.from_user.full_name}!\n\n"
            f"💰 Balance: ₹{user.wallet_balance if user else 0}\n\n"
            f"Select an option:",
            reply_markup=keyboard
        )

@dp.callback_query(F.data == "show_categories")
async def show_categories(callback: types.CallbackQuery):
    async for session in get_session():
        result = await session.execute(select(Category))
        categories = result.scalars().all()
        
        if not categories:
            await callback.message.edit_text("No categories available.")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=cat.name, callback_data=f"category_{cat.id}")]
            for cat in categories
        ] + [[InlineKeyboardButton(text="🔙 Back", callback_data="back_main")]])
        
        await callback.message.edit_text("📁 Select Category:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("category_"))
async def show_products(callback: types.CallbackQuery):
    category_id = int(callback.data.split("_")[1])
    
    async for session in get_session():
        result = await session.execute(select(Product).where(Product.category_id == category_id))
        products = result.scalars().all()
        
        if not products:
            await callback.message.edit_text("No products in this category.")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{p.name} - ₹{p.price} (Stock: {p.stock})", callback_data=f"product_{p.id}")]
            for p in products
        ] + [[InlineKeyboardButton(text="🔙 Back", callback_data="show_categories")]])
        
        await callback.message.edit_text("🛍️ Products:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def buy_product(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    
    async for session in get_session():
        product = await session.get(Product, product_id)
        user = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = user.scalar_one()
        
        if product.stock <= 0:
            await callback.answer("Out of stock!", show_alert=True)
            return
        
        if user.wallet_balance < product.price:
            await callback.answer(f"Insufficient balance!\nNeed ₹{product.price}\nBalance: ₹{user.wallet_balance}", show_alert=True)
            return
        
        # Get available account
        account = await session.execute(
            select(Account).where(Account.product_id == product_id, Account.is_sold == False)
        )
        account = account.scalar_one_or_none()
        
        if not account:
            await callback.answer("No accounts available!", show_alert=True)
            return
        
        # Process purchase
        user.wallet_balance -= product.price
        product.stock -= 1
        account.is_sold = True
        
        purchase = Purchase(
            user_id=user.id,
            product_id=product_id,
            account_id=account.id,
            amount=product.price
        )
        
        session.add(purchase)
        await session.commit()
        
        # Send account details
        await callback.message.answer(
            f"✅ Purchase Successful!\n\n"
            f"Product: {product.name}\n"
            f"Amount: ₹{product.price}\n"
            f"New Balance: ₹{user.wallet_balance}\n\n"
            f"📧 Login Details:\n"
            f"Email/ID: `{account.email}`\n"
            f"Password: `{account.password}`\n\n"
            f"⚠️ Keep this information safe!",
            parse_mode="Markdown"
        )
        
        # Notify admin
        for admin_id in ADMIN_IDS:
            await bot.send_message(
                admin_id,
                f"💰 New Purchase!\n"
                f"User: {callback.from_user.full_name} (@{callback.from_user.username})\n"
                f"Product: {product.name}\n"
                f"Amount: ₹{product.price}"
            )
    
    await callback.answer("Purchase successful!")

# ========== ADMIN PANEL ==========
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Category", callback_data="admin_add_category")],
        [InlineKeyboardButton(text="➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton(text="➕ Add Account", callback_data="admin_add_account")],
        [InlineKeyboardButton(text="📊 View All Products", callback_data="admin_view_products")],
        [InlineKeyboardButton(text="👥 View Users", callback_data="admin_view_users")],
        [InlineKeyboardButton(text="💰 Add User Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="back_main")]
    ])
    
    await callback.message.edit_text("⚙️ Admin Panel:", reply_markup=keyboard)
    await callback.answer()

# Add Category Handler
@dp.callback_query(F.data == "admin_add_category")
async def add_category_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddCategoryState.waiting_for_name)
    await callback.message.answer("📝 Send category name:")
    await callback.answer()

@dp.message(AddCategoryState.waiting_for_name)
async def add_category_name(message: types.Message, state: FSMContext):
    async for session in get_session():
        category = Category(name=message.text)
        session.add(category)
        await session.commit()
        await message.answer(f"✅ Category '{message.text}' added successfully!")
        await state.clear()
        await start_command(message)

# ========== RUN BOT ==========
async def main():
    await init_db()
    print("Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
