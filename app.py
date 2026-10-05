import os
import uuid
import re
import random
import string
import qrcode

from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from functools import wraps
from flask import Flask, render_template, request, redirect, session, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import RequestEntityTooLarge
from database import get_db_connection
from datetime import datetime


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)


# ============================================================
# FLASK SESSION SECRET KEY
# ============================================================

app.secret_key = os.getenv("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "SECRET_KEY is not configured. Please add SECRET_KEY to the .env file."
    )


# ============================================================
# SESSION COOKIE SECURITY
# ============================================================

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# ============================================================
# CSRF PROTECTION
# ============================================================

csrf = CSRFProtect(app)


# ============================================================
# RATE LIMITING
# ============================================================

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[]
)


# ============================================================
# GENERATE BOOKING REFERENCE
# ============================================================

def generate_booking_reference():

    characters = string.ascii_uppercase + string.digits

    random_code = "".join(
        random.choices(characters, k=6)
    )

    date_part = datetime.now().strftime("%Y%m%d")

    return f"MTM-{date_part}-{random_code}"


# ============================================================
# ADMIN REQUIRED DECORATOR
# ============================================================

def admin_required(function):

    @wraps(function)
    def decorated_function(*args, **kwargs):

        if not session.get("admin_logged_in"):
            return redirect("/admin-login")

        return function(*args, **kwargs)

    return decorated_function


# ============================================================
# ADMIN LOGIN SETTINGS
# ============================================================

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH = generate_password_hash(
    os.getenv("ADMIN_PASSWORD")
)


# ============================================================
# FILE UPLOAD SETTINGS
# ============================================================

UPLOAD_FOLDER = "static/images"

ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp"
}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Maximum uploaded file size = 5 MB
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


# ============================================================
# CHECK ALLOWED FILE
# ============================================================

def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


# ============================================================
# FILE TOO LARGE ERROR
# ============================================================

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(error):

    return render_template(
        "error.html",
        message="File is too large. Movie posters must be 5 MB or smaller."
    ), 413


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def home():

    connection = get_db_connection()

    movies = connection.execute("""
        SELECT *
        FROM movies
        ORDER BY id DESC
        LIMIT 3
    """).fetchall()

    connection.close()

    return render_template(
        "index.html",
        movies=movies
    )


# ============================================================
# MOVIES PAGE - SEARCH AND FILTERS
# ============================================================

@app.route("/movies")
def movies():

    connection = get_db_connection()

    # Get search and filter values
    search_query = request.args.get("q", "").strip()

    selected_genre = request.args.get(
        "genre",
        ""
    ).strip()

    selected_language = request.args.get(
        "language",
        ""
    ).strip()

    # Build SQL query safely
    query = """
        SELECT *
        FROM movies
        WHERE 1 = 1
    """

    parameters = []

    # Search by movie title or description
    if search_query:

        query += """
            AND (
                title LIKE %s
                OR description LIKE %s
            )
        """

        search_value = f"%{search_query}%"

        parameters.extend([
            search_value,
            search_value
        ])

    # Filter by genre
    if selected_genre:

        query += """
            AND genre = %s
        """

        parameters.append(selected_genre)

    # Filter by language
    if selected_language:

        query += """
            AND language = %s
        """

        parameters.append(selected_language)

    query += """
        ORDER BY id DESC
    """

    # Get filtered movies
    movies = connection.execute(
        query,
        parameters
    ).fetchall()

    # Get available genres
    genres = connection.execute("""
        SELECT DISTINCT genre
        FROM movies
        WHERE genre IS NOT NULL
        AND TRIM(genre) != ''
        ORDER BY genre
    """).fetchall()

    # Get available languages
    languages = connection.execute("""
        SELECT DISTINCT language
        FROM movies
        WHERE language IS NOT NULL
        AND TRIM(language) != ''
        ORDER BY language
    """).fetchall()

    connection.close()

    return render_template(
        "movies.html",
        movies=movies,
        genres=genres,
        languages=languages,
        search_query=search_query,
        selected_genre=selected_genre,
        selected_language=selected_language
    )


# ============================================================
# MOVIE DETAILS
# ============================================================

@app.route("/movie/<int:movie_id>")
def movie_details(movie_id):

    connection = get_db_connection()

    # Get movie details
    movie = connection.execute("""
        SELECT *
        FROM movies
        WHERE id = %s
    """, (
        movie_id,
    )).fetchone()

    # Get available shows for this movie
    shows = connection.execute("""
        SELECT *
        FROM shows
        WHERE movie_id = %s
        ORDER BY show_date, show_time
    """, (
        movie_id,
    )).fetchall()

    connection.close()

    # Movie does not exist
    if movie is None:

        return render_template(
            "error.html",
            message="Movie not found."
        )

    return render_template(
        "movie_details.html",
        movie=movie,
        shows=shows
    )


# ============================================================
# BOOK NOW
# ============================================================

@app.route("/book-now/<int:movie_id>")
def book_now(movie_id):

    connection = get_db_connection()

    movie = connection.execute("""
        SELECT *
        FROM movies
        WHERE id = %s
    """, (
        movie_id,
    )).fetchone()

    connection.close()

    if movie is None:

        return render_template(
            "error.html",
            message="Movie not found."
        )

    # Remember selected movie
    session["selected_movie_id"] = movie_id

    # User is not logged in
    if "user_id" not in session:
        return redirect("/login")

    # User is already logged in
    return redirect("/shows")


# ============================================================
# SHOWS PAGE
# ============================================================

@app.route("/shows")
def shows():

    connection = get_db_connection()

    selected_movie_id = session.get(
        "selected_movie_id"
    )

    if selected_movie_id:

        shows = connection.execute("""
            SELECT
                shows.*,
                movies.title AS movie_title,
                movies.poster
            FROM shows
            JOIN movies
                ON shows.movie_id = movies.id
            WHERE shows.movie_id = %s
            ORDER BY
                shows.show_date,
                shows.show_time
        """, (
            selected_movie_id,
        )).fetchall()

    else:

        shows = connection.execute("""
            SELECT
                shows.*,
                movies.title AS movie_title,
                movies.poster
            FROM shows
            JOIN movies
                ON shows.movie_id = movies.id
            ORDER BY
                shows.show_date,
                shows.show_time
        """).fetchall()

    connection.close()

    return render_template(
        "shows.html",
        shows=shows
    )


# ============================================================
# USER REGISTRATION
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form["name"].strip()

        email = request.form[
            "email"
        ].strip().lower()

        password = request.form["password"]

        # ----------------------------------------------------
        # CHECK EMPTY FIELDS
        # ----------------------------------------------------

        if not name or not email or not password:

            return render_template(
                "error.html",
                message="All registration fields are required."
            )

        # ----------------------------------------------------
        # CHECK NAME
        # ----------------------------------------------------

        if len(name) < 2:

            return render_template(
                "error.html",
                message="Name must contain at least 2 characters."
            )

        # ----------------------------------------------------
        # CHECK EMAIL FORMAT
        # ----------------------------------------------------

        email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

        if not re.match(
            email_pattern,
            email
        ):

            return render_template(
                "error.html",
                message="Please enter a valid email address."
            )

        # ----------------------------------------------------
        # CHECK PASSWORD LENGTH
        # ----------------------------------------------------

        if len(password) < 6:

            return render_template(
                "error.html",
                message="Password must contain at least 6 characters."
            )

        connection = get_db_connection()

        # ----------------------------------------------------
        # CHECK DUPLICATE EMAIL
        # ----------------------------------------------------

        existing_user = connection.execute("""
            SELECT id
            FROM users
            WHERE email = %s
        """, (
            email,
        )).fetchone()

        if existing_user:

            connection.close()

            return render_template(
                "error.html",
                message="An account with this email already exists."
            )

        # ----------------------------------------------------
        # HASH PASSWORD
        # ----------------------------------------------------

        hashed_password = generate_password_hash(
            password
        )

        # ----------------------------------------------------
        # INSERT USER
        # ----------------------------------------------------

        connection.execute("""
            INSERT INTO users
            (
                name,
                email,
                password
            )
            VALUES (%s, %s, %s)
        """, (
            name,
            email,
            hashed_password
        ))

        connection.commit()
        connection.close()

        return redirect("/login")

    return render_template(
        "register.html"
    )


# ============================================================
# USER LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
@limiter.limit("5 per minute")
def login():

    if request.method == "POST":

        email = request.form[
            "email"
        ].strip().lower()

        password = request.form[
            "password"
        ]

        connection = get_db_connection()

        user = connection.execute("""
            SELECT *
            FROM users
            WHERE email = %s
        """, (
            email,
        )).fetchone()

        # ----------------------------------------------------
        # USER NOT FOUND
        # ----------------------------------------------------

        if user is None:

            connection.close()

            return render_template(
                "error.html",
                message="Invalid email or password."
            )

        password_valid = False

        # ----------------------------------------------------
        # CHECK HASHED PASSWORD
        # ----------------------------------------------------

        try:

            password_valid = check_password_hash(
                user["password"],
                password
            )

        except (
            ValueError,
            TypeError
        ):

            password_valid = False

        # ----------------------------------------------------
        # BACKWARD COMPATIBILITY
        # ----------------------------------------------------

        if not password_valid:

            if user["password"] == password:

                password_valid = True

                new_hashed_password = (
                    generate_password_hash(
                        password
                    )
                )

                connection.execute("""
                    UPDATE users
                    SET password = %s
                    WHERE id = %s
                """, (
                    new_hashed_password,
                    user["id"]
                ))

                connection.commit()

        # ----------------------------------------------------
        # INVALID PASSWORD
        # ----------------------------------------------------

        if not password_valid:

            connection.close()

            return render_template(
                "error.html",
                message="Invalid email or password."
            )

        # ----------------------------------------------------
        # LOGIN SUCCESS
        # ----------------------------------------------------

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]

        connection.close()

        # Return to selected movie shows
        if session.get(
            "selected_movie_id"
        ):

            return redirect("/shows")

        return redirect("/")

    return render_template(
        "login.html"
    )


# ============================================================
# SEAT SELECTION
# ============================================================

@app.route(
    "/seats/<int:show_id>",
    methods=["GET", "POST"]
)
def seats(show_id):

    if "user_id" not in session:
        return redirect("/login")

    connection = get_db_connection()

    # --------------------------------------------------------
    # GET SHOW + SCREEN CAPACITY
    # --------------------------------------------------------

    show = connection.execute("""
        SELECT
            shows.*,
            movies.title AS movie_title,
            movies.poster,
            screens.capacity AS screen_capacity
        FROM shows
        JOIN movies
            ON shows.movie_id = movies.id
        LEFT JOIN screens
            ON shows.theatre = screens.theatre
            AND shows.screen = screens.screen_name
        WHERE shows.id = %s
    """, (
        show_id,
    )).fetchone()

    if show is None:

        connection.close()

        return render_template(
            "error.html",
            message="Show not found."
        )

    # --------------------------------------------------------
    # GET BOOKED SEATS
    # --------------------------------------------------------

    booked_rows = connection.execute("""
        SELECT seat_number
        FROM bookings
        WHERE show_id = %s
        AND booking_status = 'Confirmed'
    """, (
        show_id,
    )).fetchall()

    connection.close()

    booked_seats = [
        row["seat_number"]
        for row in booked_rows
    ]

    # --------------------------------------------------------
    # GET SCREEN CAPACITY
    # --------------------------------------------------------

    screen_capacity = show["screen_capacity"]

    # If capacity is unavailable, use the existing 40-seat layout
    if not screen_capacity:
        screen_capacity = 40

    # --------------------------------------------------------
    # CREATE AVAILABLE SEATS
    # --------------------------------------------------------

    seats_list = []

    # Maximum 8 seats per row
    seats_per_row = 8

    # Calculate number of rows required
    number_of_rows = (
        screen_capacity + seats_per_row - 1
    ) // seats_per_row

    for row_index in range(
        number_of_rows
    ):

        row_letter = chr(
            ord("A") + row_index
        )

        seats_in_this_row = min(
            seats_per_row,
            screen_capacity - (
                row_index * seats_per_row
            )
        )

        for number in range(
            1,
            seats_in_this_row + 1
        ):

            seats_list.append(
                f"{row_letter}{number}"
            )

    # --------------------------------------------------------
    # SELECT SEATS
    # --------------------------------------------------------

    if request.method == "POST":

        selected_seats = request.form.getlist(
            "seats"
        )

        # ----------------------------------------------------
        # CHECK WHETHER SEATS WERE SELECTED
        # ----------------------------------------------------

        if not selected_seats:

            return render_template(
                "error.html",
                message="Please select at least one seat."
            )

        # ----------------------------------------------------
        # REMOVE DUPLICATES
        # ----------------------------------------------------

        selected_seats = list(
            dict.fromkeys(
                selected_seats
            )
        )

        # ----------------------------------------------------
        # MAXIMUM SEATS PER BOOKING
        # ----------------------------------------------------

        if len(selected_seats) > 10:

            return render_template(
                "error.html",
                message="You can book a maximum of 10 seats at once."
            )

        # ----------------------------------------------------
        # VALIDATE SEAT NAMES
        # ----------------------------------------------------

        for seat in selected_seats:

            if seat not in seats_list:

                return render_template(
                    "error.html",
                    message="Invalid seat selection."
                )

        # ----------------------------------------------------
        # RECHECK BOOKED SEATS
        # ----------------------------------------------------

        connection = get_db_connection()

        current_booked_rows = connection.execute("""
            SELECT seat_number
            FROM bookings
            WHERE show_id = %s
            AND booking_status = 'Confirmed'
        """, (
            show_id,
        )).fetchall()

        connection.close()

        current_booked_seats = [
            row["seat_number"]
            for row in current_booked_rows
        ]

        # ----------------------------------------------------
        # CHECK SEAT AVAILABILITY AGAIN
        # ----------------------------------------------------

        for seat in selected_seats:

            if seat in current_booked_seats:

                return render_template(
                    "error.html",
                    message=(
                        f"Seat {seat} is already booked. "
                        "Please choose another seat."
                    )
                )

        # ----------------------------------------------------
        # CALCULATE TOTAL
        # ----------------------------------------------------

        total_price = (
            show["price"]
            * len(selected_seats)
        )

        # ----------------------------------------------------
        # STORE TEMPORARY BOOKING INFORMATION
        # ----------------------------------------------------
        # The seats are NOT inserted into the database yet.
        # They will be inserted only after mock payment succeeds.

        session["pending_booking"] = {
            "show_id": show_id,
            "selected_seats": selected_seats
        }

        # ----------------------------------------------------
        # GO TO PAYMENT PAGE
        # ----------------------------------------------------

        return redirect(
            f"/payment/{show_id}"
        )

    # --------------------------------------------------------
    # DISPLAY SEAT PAGE
    # --------------------------------------------------------

    return render_template(
        "seats.html",
        show=show,
        seats=seats_list,
        booked_seats=booked_seats
    )
#----------------------------------------------------
# seat availability
#----------------------------------------------------


@app.route(
    "/api/seat-availability/<int:show_id>"
)
def seat_availability(show_id):

    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401

    connection = get_db_connection()

    show = connection.execute("""
        SELECT id
        FROM shows
        WHERE id = %s
    """, (
        show_id,
    )).fetchone()

    if show is None:

        connection.close()

        return jsonify({
            "success": False,
            "message": "Show not found."
        }), 404

    booked_rows = connection.execute("""
        SELECT seat_number
        FROM bookings
        WHERE show_id = %s
        AND booking_status = 'Confirmed'
    """, (
        show_id,
    )).fetchall()

    connection.close()

    booked_seats = [
        row["seat_number"]
        for row in booked_rows
    ]

    return jsonify({
        "success": True,
        "booked_seats": booked_seats
    })

#-------------------------------------------------------
# payment
#-------------------------------------------------------


@app.route(
    "/payment/<int:show_id>",
    methods=["GET", "POST"]
)
def payment(show_id):

    if "user_id" not in session:
        return redirect("/login")

    pending_booking = session.get(
        "pending_booking"
    )

    # --------------------------------------------------------
    # CHECK PENDING BOOKING
    # --------------------------------------------------------

    if not pending_booking:

        return render_template(
            "error.html",
            message="No pending booking was found."
        )

    if pending_booking["show_id"] != show_id:

        session.pop(
            "pending_booking",
            None
        )

        return render_template(
            "error.html",
            message="Invalid booking session."
        )

    selected_seats = pending_booking[
        "selected_seats"
    ]

    # --------------------------------------------------------
    # GET SHOW INFORMATION
    # --------------------------------------------------------

    connection = get_db_connection()

    show = connection.execute("""
        SELECT
            shows.*,
            movies.title AS movie_title,
            movies.poster
        FROM shows
        JOIN movies
            ON shows.movie_id = movies.id
        WHERE shows.id = %s
    """, (
        show_id,
    )).fetchone()

    connection.close()

    if show is None:

        session.pop(
            "pending_booking",
            None
        )

        return render_template(
            "error.html",
            message="Show not found."
        )

    # --------------------------------------------------------
    # CALCULATE TOTAL
    # --------------------------------------------------------

    total_price = (
        show["price"]
        * len(selected_seats)
    )

    # --------------------------------------------------------
    # PAYMENT
    # --------------------------------------------------------

    if request.method == "POST":

        payment_method = request.form.get(
            "payment_method",
            ""
        ).strip()

        allowed_payment_methods = [
            "UPI",
            "Debit / Credit Card",
            "Net Banking"
        ]

        if payment_method not in allowed_payment_methods:

            return render_template(
                "error.html",
                message="Please select a valid payment method."
            )

        # ----------------------------------------------------
        # RECHECK SEAT AVAILABILITY
        # ----------------------------------------------------

        connection = get_db_connection()

        current_booked_rows = connection.execute("""
            SELECT seat_number
            FROM bookings
            WHERE show_id = %s
            AND booking_status = 'Confirmed'
        """, (
            show_id,
        )).fetchall()

        current_booked_seats = [
            row["seat_number"]
            for row in current_booked_rows
        ]

        for seat in selected_seats:

            if seat in current_booked_seats:

                connection.close()

                session.pop(
                    "pending_booking",
                    None
                )

                return render_template(
                    "error.html",
                    message=(
                        f"Seat {seat} was booked by another user "
                        "before payment was completed. "
                        "Please select your seats again."
                    )
                )

        # ----------------------------------------------------
        # GENERATE BOOKING INFORMATION
        # ----------------------------------------------------

        booking_date = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        booking_reference = (
            generate_booking_reference()
        )

        # ----------------------------------------------------
        # CREATE BOOKING
        # ----------------------------------------------------

        try:

            for seat in selected_seats:

                connection.execute("""
                    INSERT INTO bookings
                    (
                        user_id,
                        show_id,
                        seat_number,
                        booking_date,
                        booking_reference
                    )
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    session["user_id"],
                    show_id,
                    seat,
                    booking_date,
                    booking_reference
                ))

            connection.commit()
            connection.close()

        except Exception as error:

            try:
                connection.rollback()
                connection.close()
            except Exception:
                pass

            print(
                "Payment booking error:",
                error
            )

            session.pop(
                "pending_booking",
                None
            )

            return render_template(
                "error.html",
                message=(
                    "Payment was completed, but the booking "
                    "could not be created. Please try again."
                )
            )

        # ----------------------------------------------------
        # REMOVE TEMPORARY BOOKING DATA
        # ----------------------------------------------------

        session.pop(
            "pending_booking",
            None
        )

        # ----------------------------------------------------
        # SHOW BOOKING CONFIRMATION
        # ----------------------------------------------------

        return render_template(
            "booking_success.html",
            show=show,
            selected_seats=selected_seats,
            total_price=total_price,
            booking_reference=booking_reference
        )

    # --------------------------------------------------------
    # DISPLAY PAYMENT PAGE
    # --------------------------------------------------------

    return render_template(
        "payment.html",
        show=show,
        selected_seats=selected_seats,
        total_price=total_price
    )

# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route(
    "/admin-login",
    methods=["GET", "POST"]
)
@limiter.limit("5 per minute")
def admin_login():

    if request.method == "POST":

        username = request.form[
            "username"
        ].strip()

        password = request.form[
            "password"
        ]

        # ----------------------------------------------------
        # CHECK ADMIN USERNAME
        # ----------------------------------------------------

        if username != ADMIN_USERNAME:

            return render_template(
                "error.html",
                message="Invalid admin username or password."
            )

        # ----------------------------------------------------
        # CHECK ADMIN PASSWORD
        # ----------------------------------------------------

        if not check_password_hash(
            ADMIN_PASSWORD_HASH,
            password
        ):

            return render_template(
                "error.html",
                message="Invalid admin username or password."
            )

        # ----------------------------------------------------
        # ADMIN LOGIN SUCCESS
        # ----------------------------------------------------

        session["admin_logged_in"] = True

        return redirect("/admin")

    return render_template(
        "admin_login.html"
    )


# ============================================================
# ADMIN ADD MOVIE
# ============================================================

@app.route(
    "/admin/add-movie",
    methods=["GET", "POST"]
)
@admin_required
def add_movie():

    if request.method == "POST":

        title = request.form[
            "title"
        ].strip()

        genre = request.form[
            "genre"
        ].strip()

        language = request.form[
            "language"
        ].strip()

        duration = request.form[
            "duration"
        ].strip()

        description = request.form[
            "description"
        ].strip()

        poster = request.files.get(
            "poster"
        )

        # ----------------------------------------------------
        # VALIDATE MOVIE INFORMATION
        # ----------------------------------------------------

        if not title:

            return render_template(
                "error.html",
                message="Movie title is required."
            )

        if len(title) > 100:

            return render_template(
                "error.html",
                message=(
                    "Movie title must not exceed "
                    "100 characters."
                )
            )

        if len(genre) > 50:

            return render_template(
                "error.html",
                message=(
                    "Genre must not exceed "
                    "50 characters."
                )
            )

        if len(language) > 50:

            return render_template(
                "error.html",
                message=(
                    "Language must not exceed "
                    "50 characters."
                )
            )

        if len(duration) > 30:

            return render_template(
                "error.html",
                message=(
                    "Duration must not exceed "
                    "30 characters."
                )
            )

        if len(description) > 500:

            return render_template(
                "error.html",
                message=(
                    "Description must not exceed "
                    "500 characters."
                )
            )

        # ----------------------------------------------------
        # REQUIRED POSTER
        # ----------------------------------------------------

        if (
            poster is None
            or poster.filename == ""
        ):

            return render_template(
                "error.html",
                message="Please select a movie poster."
            )

        # ----------------------------------------------------
        # POSTER TYPE
        # ----------------------------------------------------

        if not allowed_file(
            poster.filename
        ):

            return render_template(
                "error.html",
                message=(
                    "Invalid poster format. "
                    "Use JPG, JPEG, PNG or WEBP."
                )
            )

        # ----------------------------------------------------
        # SECURE FILENAME
        # ----------------------------------------------------

        original_name = secure_filename(
            poster.filename
        )

        extension = original_name.rsplit(
            ".",
            1
        )[1].lower()

        filename = (
            str(uuid.uuid4())
            + "."
            + extension
        )

        upload_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            filename
        )

        poster.save(upload_path)

        # ----------------------------------------------------
        # INSERT MOVIE
        # ----------------------------------------------------

        connection = get_db_connection()

        connection.execute("""
            INSERT INTO movies
            (
                title,
                genre,
                language,
                duration,
                description,
                poster
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            title,
            genre,
            language,
            duration,
            description,
            filename
        ))

        connection.commit()
        connection.close()

        return redirect("/admin")

    return render_template(
        "add_movie.html"
    )


# ============================================================
# ADMIN EDIT MOVIE
# ============================================================

@app.route(
    "/admin/edit-movie/<int:movie_id>",
    methods=["GET", "POST"]
)
@admin_required
def edit_movie(movie_id):

    connection = get_db_connection()

    movie = connection.execute("""
        SELECT *
        FROM movies
        WHERE id = %s
    """, (
        movie_id,
    )).fetchone()

    connection.close()

    if movie is None:

        return render_template(
            "error.html",
            message="Movie not found."
        )

    if request.method == "POST":

        title = request.form[
            "title"
        ].strip()

        genre = request.form[
            "genre"
        ].strip()

        language = request.form[
            "language"
        ].strip()

        duration = request.form[
            "duration"
        ].strip()

        description = request.form[
            "description"
        ].strip()

        poster = request.files.get(
            "poster"
        )

        # ----------------------------------------------------
        # VALIDATE EDITED MOVIE INFORMATION
        # ----------------------------------------------------

        if not title:

            return render_template(
                "error.html",
                message="Movie title is required."
            )

        if len(title) > 100:

            return render_template(
                "error.html",
                message=(
                    "Movie title must not exceed "
                    "100 characters."
                )
            )

        if len(genre) > 50:

            return render_template(
                "error.html",
                message=(
                    "Genre must not exceed "
                    "50 characters."
                )
            )

        if len(language) > 50:

            return render_template(
                "error.html",
                message=(
                    "Language must not exceed "
                    "50 characters."
                )
            )

        if len(duration) > 30:

            return render_template(
                "error.html",
                message=(
                    "Duration must not exceed "
                    "30 characters."
                )
            )

        if len(description) > 500:

            return render_template(
                "error.html",
                message=(
                    "Description must not exceed "
                    "500 characters."
                )
            )

        poster_filename = movie["poster"]

        # ----------------------------------------------------
        # NEW POSTER
        # ----------------------------------------------------

        if poster and poster.filename:

            if not allowed_file(
                poster.filename
            ):

                return render_template(
                    "error.html",
                    message=(
                        "Invalid poster format. "
                        "Use JPG, JPEG, PNG or WEBP."
                    )
                )

            original_name = secure_filename(
                poster.filename
            )

            extension = original_name.rsplit(
                ".",
                1
            )[1].lower()

            poster_filename = (
                str(uuid.uuid4())
                + "."
                + extension
            )

            upload_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                poster_filename
            )

            poster.save(upload_path)

            # Delete old poster
            if movie["poster"]:

                old_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    movie["poster"]
                )

                if os.path.exists(
                    old_path
                ):

                    try:

                        os.remove(
                            old_path
                        )

                    except OSError:

                        pass

        # ----------------------------------------------------
        # UPDATE MOVIE
        # ----------------------------------------------------

        connection = get_db_connection()

        connection.execute("""
            UPDATE movies
            SET
                title = %s,
                genre = %s,
                language = %s,
                duration = %s,
                description = %s,
                poster = %s
            WHERE id = %s
        """, (
            title,
            genre,
            language,
            duration,
            description,
            poster_filename,
            movie_id
        ))

        connection.commit()
        connection.close()

        return redirect("/admin")

    return render_template(
        "edit_movie.html",
        movie=movie
    )


# ============================================================
# ADMIN DELETE MOVIE
# ============================================================

@app.route(
    "/admin/delete-movie/<int:movie_id>",
    methods=["POST"]
)
@admin_required
def delete_movie(movie_id):
    connection = get_db_connection()

    # --------------------------------------------------------
    # CHECK ASSOCIATED SHOWS
    # --------------------------------------------------------

    show = connection.execute("""
        SELECT id
        FROM shows
        WHERE movie_id = %s
        LIMIT 1
    """, (
        movie_id,
    )).fetchone()

    if show:

        connection.close()

        return render_template(
            "error.html",
            message=(
                "This movie cannot be deleted "
                "because shows are associated with it."
            )
        )

    # --------------------------------------------------------
    # GET MOVIE
    # --------------------------------------------------------

    movie = connection.execute("""
        SELECT poster
        FROM movies
        WHERE id = %s
    """, (
        movie_id,
    )).fetchone()

    if movie is None:

        connection.close()

        return render_template(
            "error.html",
            message="Movie not found."
        )

    # --------------------------------------------------------
    # DELETE MOVIE
    # --------------------------------------------------------

    connection.execute("""
        DELETE FROM movies
        WHERE id = %s
    """, (
        movie_id,
    ))

    connection.commit()
    connection.close()

    # --------------------------------------------------------
    # DELETE POSTER
    # --------------------------------------------------------

    if movie["poster"]:

        poster_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            movie["poster"]
        )

        if os.path.exists(
            poster_path
        ):

            try:

                os.remove(
                    poster_path
                )

            except OSError:

                pass

    return redirect("/admin")


# ============================================================
# ADMIN ADD SHOW
# ============================================================

@app.route(
    "/admin/add-show",
    methods=["GET", "POST"]
)
@admin_required
def add_show():

    connection = get_db_connection()

    # Get all movies
    movies = connection.execute("""
        SELECT *
        FROM movies
        ORDER BY title
    """).fetchall()

    # Get all managed screens
    screens = connection.execute("""
        SELECT *
        FROM screens
        ORDER BY theatre, screen_name
    """).fetchall()

    if request.method == "POST":

        movie_id = request.form.get(
            "movie_id",
            ""
        ).strip()

        screen_id = request.form.get(
            "screen_id",
            ""
        ).strip()

        show_date = request.form.get(
            "show_date",
            ""
        ).strip()

        show_time = request.form.get(
            "show_time",
            ""
        ).strip()

        price = request.form.get(
            "price",
            ""
        ).strip()

        # -----------------------------
        # Validate Movie
        # -----------------------------

        if not movie_id.isdigit():

            connection.close()

            return render_template(
                "error.html",
                message="Please select a valid movie."
            )

        movie = connection.execute("""
            SELECT *
            FROM movies
            WHERE id = %s
        """, (
            int(movie_id),
        )).fetchone()

        if movie is None:

            connection.close()

            return render_template(
                "error.html",
                message="Selected movie does not exist."
            )

        # -----------------------------
        # Validate Screen
        # -----------------------------

        if not screen_id.isdigit():

            connection.close()

            return render_template(
                "error.html",
                message="Please select a valid screen."
            )

        selected_screen = connection.execute("""
            SELECT *
            FROM screens
            WHERE id = %s
        """, (
            int(screen_id),
        )).fetchone()

        if selected_screen is None:

            connection.close()

            return render_template(
                "error.html",
                message="Selected screen does not exist."
            )

        # Get theatre and screen automatically
        theatre = selected_screen["theatre"]

        screen_name = selected_screen[
            "screen_name"
        ]

        # -----------------------------
        # Validate Date
        # -----------------------------

        if not show_date:

            connection.close()

            return render_template(
                "error.html",
                message="Show date is required."
            )

        try:

            datetime.strptime(
                show_date,
                "%Y-%m-%d"
            )

        except ValueError:

            connection.close()

            return render_template(
                "error.html",
                message="Invalid show date."
            )

        # -----------------------------
        # Validate Time
        # -----------------------------

        if not show_time:

            connection.close()

            return render_template(
                "error.html",
                message="Show time is required."
            )

        # -----------------------------
        # Validate Price
        # -----------------------------

        try:

            price_value = float(price)

            if price_value <= 0:
                raise ValueError

            if price_value > 10000:
                raise ValueError

        except ValueError:

            connection.close()

            return render_template(
                "error.html",
                message="Ticket price must be between ₹1 and ₹10,000."
            )

        # -----------------------------
        # CHECK SHOWTIME CONFLICT
        # -----------------------------

        existing_show = connection.execute("""
            SELECT id
            FROM shows
            WHERE theatre = %s
            AND screen = %s
            AND show_date = %s
            AND show_time = %s
        """, (
            theatre,
            screen_name,
            show_date,
            show_time
        )).fetchone()

        if existing_show is not None:

            connection.close()

            return render_template(
                "error.html",
                message=(
                    "This screen already has a show scheduled "
                    "at the selected date and time."
                )
            )

        # -----------------------------
        # Insert Show
        # -----------------------------

        connection.execute("""
            INSERT INTO shows
            (
                movie_id,
                theatre,
                screen,
                show_date,
                show_time,
                price
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            int(movie_id),
            theatre,
            screen_name,
            show_date,
            show_time,
            price_value
        ))

        connection.commit()
        connection.close()

        return redirect("/admin")

    connection.close()

    return render_template(
        "add_show.html",
        movies=movies,
        screens=screens
    )


# ============================================================
# ADMIN DELETE SHOW
# ============================================================

@app.route(
    "/admin/delete-show/<int:show_id>",
    methods=["POST"]
)
@admin_required
def delete_show(show_id):

    connection = get_db_connection()

    # --------------------------------------------------------
    # CHECK BOOKINGS
    # --------------------------------------------------------

    booking = connection.execute("""
        SELECT id
        FROM bookings
        WHERE show_id = %s
        LIMIT 1
    """, (
        show_id,
    )).fetchone()

    if booking:

        connection.close()

        return render_template(
            "error.html",
             message=(
                "This show cannot be deleted "
                "because bookings are associated with it."
            ),
             back_url="/admin"
    )

    # --------------------------------------------------------
    # CHECK SHOW
    # --------------------------------------------------------

    show = connection.execute("""
        SELECT id
        FROM shows
        WHERE id = %s
    """, (
        show_id,
    )).fetchone()

    if show is None:

        connection.close()

    return render_template(
        "error.html",
        message="Show not found.",
        back_url="/admin"
    )

    # --------------------------------------------------------
    # DELETE SHOW
    # --------------------------------------------------------

    connection.execute("""
        DELETE FROM shows
        WHERE id = %s
    """, (
        show_id,
    ))

    connection.commit()
    connection.close()

    return redirect("/admin")


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@admin_required
def admin():

    connection = get_db_connection()

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    users = connection.execute("""
        SELECT *
        FROM users
        ORDER BY id DESC
    """).fetchall()

    # --------------------------------------------------------
    # MOVIES
    # --------------------------------------------------------

    movies = connection.execute("""
        SELECT *
        FROM movies
        ORDER BY id DESC
    """).fetchall()

    # --------------------------------------------------------
    # SHOWS
    # --------------------------------------------------------

    shows = connection.execute("""
        SELECT
            shows.*,
            movies.title AS movie_title
        FROM shows
        JOIN movies
            ON shows.movie_id = movies.id
        ORDER BY
            shows.show_date,
            shows.show_time
    """).fetchall()

    # --------------------------------------------------------
    # BOOKINGS
    # --------------------------------------------------------

    bookings = connection.execute("""
        SELECT
            bookings.id,
            bookings.seat_number,
            bookings.booking_date,
            bookings.booking_reference,
            bookings.booking_status,
            bookings.cancelled_at,
            users.name AS user_name,
            users.email,
            movies.title AS movie_title,
            shows.theatre,
            shows.show_date,
            shows.show_time,
            shows.price
        FROM bookings
        JOIN users
            ON bookings.user_id = users.id
        JOIN shows
            ON bookings.show_id = shows.id
        JOIN movies
            ON shows.movie_id = movies.id
        ORDER BY bookings.id DESC
    """).fetchall()

    # --------------------------------------------------------
    # ADMIN ANALYTICS
    # --------------------------------------------------------

    total_users = connection.execute("""
        SELECT COUNT(*) AS value
        FROM users
    """).fetchone()["value"]

    total_movies = connection.execute("""
        SELECT COUNT(*) AS value
        FROM movies
    """).fetchone()["value"]

    total_shows = connection.execute("""
        SELECT COUNT(*) AS value
        FROM shows
    """).fetchone()["value"]

    total_bookings = connection.execute("""
        SELECT COUNT(*) AS value
        FROM bookings
    """).fetchone()["value"]

    confirmed_bookings = connection.execute("""
        SELECT COUNT(*) AS value
        FROM bookings
        WHERE booking_status = 'Confirmed'
    """).fetchone()["value"]

    cancelled_bookings = connection.execute("""
        SELECT COUNT(*) AS value
        FROM bookings
        WHERE booking_status = 'Cancelled'
    """).fetchone()["value"]

    total_revenue = connection.execute("""
        SELECT COALESCE(SUM(shows.price), 0) AS value
        FROM bookings
        JOIN shows
            ON bookings.show_id = shows.id
        WHERE bookings.booking_status = 'Confirmed'
    """).fetchone()["value"]

    today_bookings = connection.execute("""
        SELECT COUNT(*) AS value
        FROM bookings
        WHERE CAST(booking_date AS DATE) = CURRENT_DATE
    """).fetchone()["value"]

    connection.close()

    # --------------------------------------------------------
    # SEND DATA TO ADMIN PAGE
    # --------------------------------------------------------

    return render_template(
        "admin.html",
        users=users,
        movies=movies,
        shows=shows,
        bookings=bookings,

        # Analytics
        total_users=total_users,
        total_movies=total_movies,
        total_shows=total_shows,
        total_bookings=total_bookings,
        confirmed_bookings=confirmed_bookings,
        cancelled_bookings=cancelled_bookings,
        total_revenue=total_revenue,
        today_bookings=today_bookings
    )


# ============================================================
# ADMIN - SCREEN MANAGEMENT
# ============================================================

@app.route(
    "/admin/screens",
    methods=["GET", "POST"]
)
@admin_required
def manage_screens():

    connection = get_db_connection()

    # =========================
    # ADD NEW SCREEN
    # =========================

    if request.method == "POST":

        theatre = request.form.get(
            "theatre",
            ""
        ).strip()

        screen_name = request.form.get(
            "screen_name",
            ""
        ).strip()

        capacity = request.form.get(
            "capacity",
            ""
        ).strip()

        # Theatre validation
        if not theatre:

            connection.close()

            return render_template(
                "error.html",
                message="Theatre name is required."
            )

        if len(theatre) > 100:

            connection.close()

            return render_template(
                "error.html",
                message="Theatre name must not exceed 100 characters."
            )

        # Screen name validation
        if not screen_name:

            connection.close()

            return render_template(
                "error.html",
                message="Screen / Auditorium name is required."
            )

        if len(screen_name) > 50:

            connection.close()

            return render_template(
                "error.html",
                message="Screen name must not exceed 50 characters."
            )

        # Capacity validation
        try:

            capacity_value = int(capacity)

        except (
            ValueError,
            TypeError
        ):

            connection.close()

            return render_template(
                "error.html",
                message="Seat capacity must be a valid number."
            )

        if capacity_value < 1:

            connection.close()

            return render_template(
                "error.html",
                message="Seat capacity must be at least 1."
            )

        if capacity_value > 500:

            connection.close()

            return render_template(
                "error.html",
                message="Seat capacity cannot exceed 500."
            )

        # =========================
        # INSERT SCREEN
        # =========================

        try:

            connection.execute("""
                INSERT INTO screens
                (
                    theatre,
                    screen_name,
                    capacity
                )
                VALUES (%s, %s, %s)
            """, (
                theatre,
                screen_name,
                capacity_value
            ))

            connection.commit()

        except Exception as error:

            connection.rollback()
            connection.close()

            return render_template(
                "error.html",
                message=f"Unable to add screen: {error}"
            )

    # =========================
    # GET ALL SCREENS
    # =========================

    screens = connection.execute("""
        SELECT *
        FROM screens
        ORDER BY theatre, id
    """).fetchall()

    connection.close()

    return render_template(
        "screens.html",
        screens=screens
    )


# ============================================================
# ADMIN - DELETE SCREEN
# ============================================================

@app.route(
    "/admin/delete-screen/<int:screen_id>",
    methods=["POST"]
)
@admin_required
def delete_screen(screen_id):
    
    connection = get_db_connection()

    # Check whether the screen exists
    screen = connection.execute("""
        SELECT *
        FROM screens
        WHERE id = %s
    """, (
        screen_id,
    )).fetchone()

    if screen is None:

        connection.close()

        return render_template(
            "error.html",
            message="Screen not found."
        )

    try:

        connection.execute("""
            DELETE FROM screens
            WHERE id = %s
        """, (
            screen_id,
        ))

        connection.commit()

    except Exception as error:

        connection.rollback()
        connection.close()

        return render_template(
            "error.html",
            message=f"Unable to delete screen: {error}"
        )

    connection.close()

    return redirect("/admin/screens")


# ============================================================
# ADMIN DELETE BOOKING
# ============================================================

@app.route(
    "/admin/delete-booking/<int:booking_id>",
    methods=["POST"]
)
@admin_required
def delete_booking(booking_id):

    connection = get_db_connection()

    booking = connection.execute("""
        SELECT id
        FROM bookings
        WHERE id = %s
    """, (
        booking_id,
    )).fetchone()

    if booking is None:

        connection.close()

        return render_template(
            "error.html",
            message="Booking not found."
        )

    connection.execute("""
        DELETE FROM bookings
        WHERE id = %s
    """, (
        booking_id,
    ))

    connection.commit()
    connection.close()

    return redirect("/admin")


# ============================================================
# MY BOOKINGS
# ============================================================

@app.route("/my-bookings")
def my_bookings():

    if "user_id" not in session:
        return redirect("/login")

    connection = get_db_connection()

    bookings = connection.execute("""
        SELECT
            MIN(bookings.id) AS booking_id,

            MAX(bookings.booking_reference)
                AS booking_reference,

            movies.title AS movie_title,

            movies.poster,

            shows.theatre,

            shows.screen,

            shows.show_date,

            shows.show_time,

            STRING_AGG(
                bookings.seat_number,
                ', '
            ) AS seat_numbers,

            SUM(shows.price) AS total_price,

            MAX(bookings.booking_date)
                AS booking_date,

            MAX(bookings.booking_status)
                AS booking_status,

            MAX(bookings.cancelled_at)
                AS cancelled_at

        FROM bookings

        JOIN shows
            ON bookings.show_id = shows.id

        JOIN movies
            ON shows.movie_id = movies.id

        WHERE bookings.user_id = %s

        GROUP BY
            bookings.show_id,
            bookings.booking_reference,
            movies.title,
            movies.poster,
            shows.theatre,
            shows.screen,
            shows.show_date,
            shows.show_time

        ORDER BY
            booking_id DESC

    """, (
        session["user_id"],
    )).fetchall()

    connection.close()

    return render_template(
        "my_bookings.html",
        bookings=bookings
    )


# ============================================================
# USER PROFILE
# ============================================================

@app.route("/profile")
def profile():

    if "user_id" not in session:
        return redirect("/login")

    connection = get_db_connection()

    user = connection.execute("""
        SELECT
            id,
            name,
            email
        FROM users
        WHERE id = %s
    """, (
        session["user_id"],
    )).fetchone()

    connection.close()

    if user is None:

        session.clear()

        return redirect("/login")

    return render_template(
        "profile.html",
        user=user
    )


# ============================================================
# VIEW TICKET
# ============================================================

@app.route(
    "/view-ticket/<int:booking_id>"
)
def view_ticket(booking_id):

    if "user_id" not in session:
        return redirect("/login")

    connection = get_db_connection()

    booking = connection.execute("""
        SELECT
            bookings.id AS booking_id,
            bookings.show_id,
            bookings.booking_date,
            bookings.booking_reference,
            movies.title AS movie_title,
            movies.poster,
            shows.theatre,
            shows.screen,
            shows.show_date,
            shows.show_time,
            shows.price
        FROM bookings
        JOIN shows
            ON bookings.show_id = shows.id
        JOIN movies
            ON shows.movie_id = movies.id
        WHERE bookings.id = %s
        AND bookings.user_id = %s
    """, (
        booking_id,
        session["user_id"]
    )).fetchone()

    if booking is None:

        connection.close()

        return render_template(
            "error.html",
            message="Booking not found."
        )

    seats = connection.execute("""
        SELECT
            seat_number
        FROM bookings
        WHERE user_id = %s
        AND show_id = %s
        AND booking_reference = %s
        ORDER BY seat_number
    """, (
        session["user_id"],
        booking["show_id"],
        booking["booking_reference"]
    )).fetchall()

    connection.close()

    seat_numbers = [
        seat["seat_number"]
        for seat in seats
    ]

    total_price = (
        booking["price"]
        * len(seat_numbers)
    )

    # ========================================================
    # GENERATE QR CODE
    # ========================================================

    qr_data = f"""
MovieTicket

Booking Reference: {booking["booking_reference"]}

Movie: {booking["movie_title"]}

Theatre: {booking["theatre"]}

Screen: {booking["screen"]}

Date: {booking["show_date"]}

Time: {booking["show_time"]}

Seats: {", ".join(seat_numbers)}

Total Amount: ₹{total_price}
"""

    qr = qrcode.make(qr_data)

    # ========================================================
    # QR CODE FILE NAME
    # ========================================================

    qr_filename = (
        f"{booking['booking_reference']}.png"
    )

    # ========================================================
    # QR CODE FILE PATH
    # ========================================================

    qr_path = os.path.join(
        app.root_path,
        "static",
        "qr_codes",
        qr_filename
    )

    # ========================================================
    # SAVE QR CODE
    # ========================================================

    qr.save(qr_path)

    # ========================================================
    # DISPLAY TICKET
    # ========================================================

    return render_template(
        "view_ticket.html",
        booking=booking,
        seat_numbers=seat_numbers,
        total_price=total_price,
        qr_filename=qr_filename
    )


# ============================================================
# CANCEL BOOKING
# ============================================================

@app.route("/cancel-booking/<int:booking_id>", methods=["POST"])
def cancel_booking(booking_id):

    if "user_id" not in session:
        return redirect("/login")

    connection = get_db_connection()

    booking = connection.execute("""
        SELECT
            id,
            show_id,
            booking_reference,
            booking_status
        FROM bookings
        WHERE id = %s
        AND user_id = %s
    """, (
        booking_id,
        session["user_id"]
    )).fetchone()

    if booking is None:

        connection.close()

        return render_template(
            "error.html",
            message="Booking not found."
        )

    if booking["booking_status"] == "Cancelled":

        connection.close()

        return redirect("/my-bookings")

    try:

        cancellation_time = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # Cancel every seat belonging to this booking
        connection.execute("""
            UPDATE bookings
            SET
                booking_status = 'Cancelled',
                cancelled_at = %s
            WHERE user_id = %s
            AND show_id = %s
            AND booking_reference = %s
        """, (
            cancellation_time,
            session["user_id"],
            booking["show_id"],
            booking["booking_reference"]
        ))

        connection.commit()

    except Exception as error:

        connection.rollback()
        connection.close()

        print("Cancellation error:", error)

        return render_template(
            "error.html",
            message="Unable to cancel the booking. Please try again."
        )

    connection.close()

    return redirect("/my-bookings")


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.route("/admin-logout")
def admin_logout():

    session.pop(
        "admin_logged_in",
        None
    )

    return redirect("/admin-login")


# ============================================================
# USER LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )