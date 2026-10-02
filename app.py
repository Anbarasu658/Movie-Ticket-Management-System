import os
import uuid
import re

from dotenv import load_dotenv
from functools import wraps

from flask import Flask, render_template, request, redirect, session
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

app.secret_key = os.getenv(
    "SECRET_KEY",
    "temporary-development-key"
)


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

ADMIN_USERNAME = "admin"

ADMIN_PASSWORD_HASH = generate_password_hash(
    "admin123"
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
# MOVIES PAGE
# ============================================================

@app.route("/movies")
def movies():

    connection = get_db_connection()

    movies = connection.execute("""
        SELECT *
        FROM movies
        ORDER BY id DESC
    """).fetchall()

    connection.close()

    return render_template(
        "movies.html",
        movies=movies
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
        WHERE id = ?
    """, (movie_id,)).fetchone()

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
            WHERE shows.movie_id = ?
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
        email = request.form["email"].strip().lower()
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
            WHERE email = ?
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
            VALUES (?, ?, ?)
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
def login():

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        connection = get_db_connection()

        user = connection.execute("""
            SELECT *
            FROM users
            WHERE email = ?
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
                    SET password = ?
                    WHERE id = ?
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
    # GET SHOW
    # --------------------------------------------------------

    show = connection.execute("""
        SELECT
            shows.*,
            movies.title AS movie_title,
            movies.poster
        FROM shows
        JOIN movies
            ON shows.movie_id = movies.id
        WHERE shows.id = ?
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
        WHERE show_id = ?
    """, (
        show_id,
    )).fetchall()

    connection.close()

    booked_seats = [
        row["seat_number"]
        for row in booked_rows
    ]

    # --------------------------------------------------------
    # CREATE AVAILABLE SEATS
    # --------------------------------------------------------

    seats_list = []

    for row in [
        "A",
        "B",
        "C",
        "D",
        "E"
    ]:

        for number in range(1, 9):

            seats_list.append(
                f"{row}{number}"
            )

    # --------------------------------------------------------
    # BOOK SEATS
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
        #
        # This prevents a seat from being booked if another
        # booking happened after the seat page was opened.
        # ----------------------------------------------------

        connection = get_db_connection()

        current_booked_rows = connection.execute("""
            SELECT seat_number
            FROM bookings
            WHERE show_id = ?
        """, (
            show_id,
        )).fetchall()

        current_booked_seats = [
            row["seat_number"]
            for row in current_booked_rows
        ]

        # ----------------------------------------------------
        # CHECK SEAT AVAILABILITY AGAIN
        # ----------------------------------------------------

        for seat in selected_seats:

            if seat in current_booked_seats:

                connection.close()

                return render_template(
                    "error.html",
                    message=(
                        f"Seat {seat} is already booked. "
                        "Please choose another seat."
                    )
                )

        # ----------------------------------------------------
        # BOOKING DATE
        # ----------------------------------------------------

        booking_date = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # ----------------------------------------------------
        # INSERT BOOKINGS
        # ----------------------------------------------------

        try:

            for seat in selected_seats:

                connection.execute("""
                    INSERT INTO bookings
                    (
                        user_id,
                        show_id,
                        seat_number,
                        booking_date
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    session["user_id"],
                    show_id,
                    seat,
                    booking_date
                ))

            connection.commit()
            connection.close()

        except Exception:

            try:

                connection.rollback()
                connection.close()

            except Exception:

                pass

            return render_template(
                "error.html",
                message=(
                    "One or more selected seats are no longer "
                    "available. Please select your seats again."
                )
            )

        # ----------------------------------------------------
        # CALCULATE TOTAL
        # ----------------------------------------------------

        total_price = (
            show["price"]
            * len(selected_seats)
        )

        return render_template(
            "booking_success.html",
            show=show,
            selected_seats=selected_seats,
            total_price=total_price
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


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route(
    "/admin-login",
    methods=["GET", "POST"]
)
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
        # STEP 14.8
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
            VALUES (?, ?, ?, ?, ?, ?)
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
        WHERE id = ?
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
                title = ?,
                genre = ?,
                language = ?,
                duration = ?,
                description = ?,
                poster = ?
            WHERE id = ?
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
    "/admin/delete-movie/<int:movie_id>"
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
        WHERE movie_id = ?
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
        WHERE id = ?
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
        WHERE id = ?
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

    movies = connection.execute("""
        SELECT *
        FROM movies
        ORDER BY title
    """).fetchall()

    connection.close()

    if request.method == "POST":

        movie_id = request.form["movie_id"].strip()
        theatre = request.form["theatre"].strip()
        show_date = request.form["show_date"].strip()
        show_time = request.form["show_time"].strip()
        price = request.form["price"].strip()

        # ----------------------------------------------------
        # VALIDATE THEATRE
        # ----------------------------------------------------

        if not theatre:

            return render_template(
                "error.html",
                message="Theatre name is required."
            )

        if len(theatre) > 100:

            return render_template(
                "error.html",
                message="Theatre name must not exceed 100 characters."
            )

        # ----------------------------------------------------
        # VALIDATE MOVIE ID
        # ----------------------------------------------------

        try:

            movie_id = int(movie_id)

        except ValueError:

            return render_template(
                "error.html",
                message="Invalid movie selected."
            )

        # ----------------------------------------------------
        # VALIDATE DATE
        # ----------------------------------------------------

        if not show_date:

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

            return render_template(
                "error.html",
                message="Invalid show date."
            )

        # ----------------------------------------------------
        # VALIDATE TIME
        # ----------------------------------------------------

        if not show_time:

            return render_template(
                "error.html",
                message="Show time is required."
            )

        # ----------------------------------------------------
        # VALIDATE PRICE
        # ----------------------------------------------------

        try:

            price = float(price)

        except ValueError:

            return render_template(
                "error.html",
                message="Ticket price must be a valid number."
            )

        if price <= 0:

            return render_template(
                "error.html",
                message="Ticket price must be greater than zero."
            )

        if price > 10000:

            return render_template(
                "error.html",
                message="Ticket price must not exceed ₹10,000."
            )

        # ----------------------------------------------------
        # CHECK MOVIE EXISTS
        # ----------------------------------------------------

        connection = get_db_connection()

        movie = connection.execute("""
            SELECT id
            FROM movies
            WHERE id = ?
        """, (
            movie_id,
        )).fetchone()

        if movie is None:

            connection.close()

            return render_template(
                "error.html",
                message="Selected movie does not exist."
            )

        # ----------------------------------------------------
        # INSERT SHOW
        # ----------------------------------------------------

        connection.execute("""
            INSERT INTO shows
            (
                movie_id,
                theatre,
                show_date,
                show_time,
                price
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            movie_id,
            theatre,
            show_date,
            show_time,
            price
        ))

        connection.commit()
        connection.close()

        return redirect("/admin")

    return render_template(
        "add_show.html",
        movies=movies
    )


# ============================================================
# ADMIN DELETE SHOW
# ============================================================

@app.route(
    "/admin/delete-show/<int:show_id>"
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
        WHERE show_id = ?
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
            )
        )

    # --------------------------------------------------------
    # CHECK SHOW
    # --------------------------------------------------------

    show = connection.execute("""
        SELECT id
        FROM shows
        WHERE id = ?
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
    # DELETE SHOW
    # --------------------------------------------------------

    connection.execute("""
        DELETE FROM shows
        WHERE id = ?
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

    connection.close()

    return render_template(
        "admin.html",
        users=users,
        movies=movies,
        shows=shows,
        bookings=bookings
    )


# ============================================================
# ADMIN DELETE BOOKING
# ============================================================

@app.route(
    "/admin/delete-booking/<int:booking_id>"
)
@admin_required
def delete_booking(booking_id):

    connection = get_db_connection()

    booking = connection.execute("""
        SELECT id
        FROM bookings
        WHERE id = ?
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
        WHERE id = ?
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
            movies.title AS movie_title,
            movies.poster,
            shows.theatre,
            shows.show_date,
            shows.show_time,
            GROUP_CONCAT(
                bookings.seat_number,
                ', '
            ) AS seat_numbers,
            SUM(shows.price) AS total_price,
            MAX(bookings.booking_date) AS booking_date
        FROM bookings
        JOIN shows
            ON bookings.show_id = shows.id
        JOIN movies
            ON shows.movie_id = movies.id
        WHERE bookings.user_id = ?
        GROUP BY
            bookings.show_id,
            bookings.booking_date
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
# VIEW TICKET
# ============================================================

@app.route(
    "/view-ticket/<int:booking_id>"
)
def view_ticket(booking_id):

    if "user_id" not in session:

        return redirect("/login")

    connection = get_db_connection()

    # --------------------------------------------------------
    # GET SELECTED BOOKING
    # --------------------------------------------------------

    booking = connection.execute("""
        SELECT
            bookings.id AS booking_id,
            bookings.show_id,
            bookings.booking_date,
            movies.title AS movie_title,
            movies.poster,
            shows.theatre,
            shows.show_date,
            shows.show_time,
            shows.price
        FROM bookings
        JOIN shows
            ON bookings.show_id = shows.id
        JOIN movies
            ON shows.movie_id = movies.id
        WHERE bookings.id = ?
        AND bookings.user_id = ?
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

    # --------------------------------------------------------
    # GET ALL SEATS FROM THIS BOOKING
    # --------------------------------------------------------

    seats = connection.execute("""
        SELECT seat_number
        FROM bookings
        WHERE user_id = ?
        AND show_id = ?
        AND booking_date = ?
        ORDER BY seat_number
    """, (
        session["user_id"],
        booking["show_id"],
        booking["booking_date"]
    )).fetchall()

    connection.close()

    seat_numbers = [
        seat["seat_number"]
        for seat in seats
    ]

    # --------------------------------------------------------
    # TOTAL PRICE
    # --------------------------------------------------------

    total_price = (
        booking["price"]
        * len(seat_numbers)
    )

    return render_template(
        "view_ticket.html",
        booking=booking,
        seat_numbers=seat_numbers,
        total_price=total_price
    )


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
        debug=True
    )