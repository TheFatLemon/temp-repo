import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    rows = db.execute(
        "SELECT symbol, SUM(shares) as total_shares FROM transactions WHERE user_id = ? GROUP BY symbol",
        session["user_id"]
    )

    holdings = []
    grand_total = 0

    for row in rows:
        if row["total_shares"] > 0:
            stock = lookup(row["symbol"])
            current_price = stock["price"]
            total_value = row["total_shares"] * current_price
            grand_total += total_value
            holdings.append({
                "symbol": row["symbol"],
                "name": stock["name"],
                "shares": row["total_shares"],
                "price": current_price,
                "total": total_value
            })

    cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
    grand_total += cash

    return render_template("index.html", holdings=holdings, cash=cash, grand_total=grand_total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "POST":

        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        if not symbol:
            return apology("must provide symbol")
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("shares must be a positive integer")

        shares = int(shares)

        stock = lookup(symbol.upper())
        if stock is None:
            return apology("invalid symbol")

        price = stock["price"]
        cost = shares * price

        user = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]
        cash = user["cash"]

        if cost > cash:
            return apology("not enough cash")

        db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", cost, session["user_id"])

        db.execute(
            "INSERT INTO transactions (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
            session["user_id"], stock["symbol"], shares, price
        )

        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    rows = db.execute(
        "SELECT symbol, shares, price, transacted FROM transactions WHERE user_id = ? ORDER BY transacted DESC",
        session["user_id"]
    )

    return render_template("history.html", transactions=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    session.clear()

    if request.method == "POST":

        if not request.form.get("username"):
            return apology("must provide username", 403)

        elif not request.form.get("password"):
            return apology("must provide password", 403)

        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        session["user_id"] = rows[0]["id"]

        return redirect("/")

    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    session.clear()

    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    if request.method == "POST":
        symbol = request.form.get("symbol")

        if not symbol:
            return apology("must provide symbol")

        stock = lookup(symbol.upper())

        if stock is None:
            return apology("invalid symbol")

        return render_template("quoted.html", stock=stock)

    return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username:
            return apology("must provide username")
        if not password or not confirmation:
            return apology("must provide password")
        if password != confirmation:
            return apology("passwords don’t match")

        rows = db.execute("SELECT * FROM users WHERE username = ?", username)
        if len(rows) > 0:
            return apology("username already taken")

        hash = generate_password_hash(password)

        db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", username, hash)

        user_id = db.execute("SELECT id FROM users WHERE username = ?", username)[0]["id"]
        session["user_id"] = user_id

        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        if not symbol:
            return apology("must provide symbol")
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("shares must be a positive integer")
        shares = int(shares)

        row = db.execute(
            "SELECT SUM(shares) as total_shares FROM transactions WHERE user_id = ? AND symbol = ?",
            session["user_id"], symbol
        )[0]

        if row["total_shares"] is None or row["total_shares"] < shares:
            return apology("not enough shares")

        stock = lookup(symbol.upper())
        price = stock["price"]
        proceeds = shares * price

        db.execute("UPDATE users SET cash = cash + ? WHERE id = ?", proceeds, session["user_id"])

        db.execute(
            "INSERT INTO transactions (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
            session["user_id"], stock["symbol"], -shares, price
        )

        return redirect("/")

    else:
        rows = db.execute(
            "SELECT symbol FROM transactions WHERE user_id = ? GROUP BY symbol HAVING SUM(shares) > 0",
            session["user_id"]
        )
        return render_template("sell.html", symbols=[row["symbol"] for row in rows])


@app.route("/add_cash", methods=["GET", "POST"])
@login_required
def add_cash():
    if request.method == "POST":
        # Get the amount the user wants to add
        amount = request.form.get("amount")

        # Validate input
        if not amount:
            return apology("must provide amount")
        try:
            amount = float(amount)
            if amount <= 0:
                return apology("amount must be positive")
        except ValueError:
            return apology("invalid amount")

        # Update user's cash
        db.execute("UPDATE users SET cash = cash + ? WHERE id = ?", amount, session["user_id"])

        # Optionally, record this as a transaction with symbol "CASH"
        db.execute(
            "INSERT INTO transactions (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
            session["user_id"], "CASH", 0, amount
        )

        return redirect("/")

    else:
        return render_template("add_cash.html")
