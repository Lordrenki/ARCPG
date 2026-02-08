from arkpg.core.config import Settings


def test_resolved_database_url_prefers_db_parts_mysql() -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        DB_HOST="us.mysql.db.bot-hosting.net",
        DB_PORT=3306,
        DB_NAME="game",
        DB_USER="botuser",
        DB_PASSWORD="p@ss/word:+",
    )

    assert settings.resolved_database_url.startswith("mysql+aiomysql://botuser:")
    assert "p%40ss%2Fword%3A+" in settings.resolved_database_url
    assert settings.resolved_database_url.endswith("@us.mysql.db.bot-hosting.net:3306/game")


def test_resolved_database_url_prefers_db_parts_postgres_when_database_url_is_postgres() -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        DATABASE_URL="postgresql+asyncpg://ignored:ignored@localhost:5432/ignored",
        DB_HOST="db.example.com",
        DB_PORT=5432,
        DB_NAME="game",
        DB_USER="botuser",
        DB_PASSWORD="secret",
    )

    assert settings.resolved_database_url.startswith("postgresql+asyncpg://botuser:secret@db.example.com:5432/game")


def test_database_settings_validation_accepts_database_url_only() -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        DATABASE_URL="mysql+aiomysql://u:p@host:3306/db",
        DB_HOST=None,
        DB_PORT=None,
        DB_NAME=None,
        DB_USER=None,
        DB_PASSWORD=None,
    )

    assert settings.resolved_database_url == "mysql+aiomysql://u:p@host:3306/db"


def test_resolved_database_url_supports_host_panel_mysql_aliases() -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        MYSQL_HOST="us.mysql.db.bot-hosting.net",
        MYSQL_PORT=3306,
        MYSQL_DATABASE="game",
        MYSQL_USER="botuser",
        MYSQL_PASSWORD="p@ss/word:+",
    )

    assert settings.resolved_database_url.startswith("mysql+aiomysql://botuser:")
    assert "p%40ss%2Fword%3A+" in settings.resolved_database_url
    assert settings.resolved_database_url.endswith("@us.mysql.db.bot-hosting.net:3306/game")


def test_resolved_database_url_strips_wrapping_quotes_from_db_values() -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        DB_HOST='"us.mysql.db.bot-hosting.net"',
        DB_PORT=3306,
        DB_NAME="'game'",
        DB_USER='"botuser"',
        DB_PASSWORD="'secret'",
    )

    assert settings.resolved_database_url == "mysql+aiomysql://botuser:secret@us.mysql.db.bot-hosting.net:3306/game"


def test_resolved_database_url_strips_unbalanced_quotes_from_db_values() -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        DB_HOST="us.mysql.db.bot-hosting.net",
        DB_PORT=3306,
        DB_NAME="u552592_JveQ8r1j7d'",
        DB_USER="u552592_JveQ8r1j7d'",
        DB_PASSWORD="secret",
    )

    assert settings.resolved_database_url == "mysql+aiomysql://u552592_JveQ8r1j7d:secret@us.mysql.db.bot-hosting.net:3306/u552592_JveQ8r1j7d"


def test_resolved_database_url_strips_quotes_when_using_database_url_only() -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        DATABASE_URL="mysql+aiomysql://u552592_JveQ8r1j7d':secret@us.mysql.db.bot-hosting.net:3306/u552592_JveQ8r1j7d'",
        DB_HOST=None,
        DB_PORT=None,
        DB_NAME=None,
        DB_USER=None,
        DB_PASSWORD=None,
    )

    assert (
        settings.resolved_database_url
        == "mysql+aiomysql://u552592_JveQ8r1j7d:secret@us.mysql.db.bot-hosting.net:3306/u552592_JveQ8r1j7d"
    )
