from typing import Optional

import databases
import pytest
import sqlalchemy

import ormar
from tests.settings import DATABASE_URL

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()


class BaseMeta(ormar.ModelMeta):
    metadata = metadata
    database = database


class Author(ormar.Model):
    class Meta(BaseMeta):
        tablename = "authors"

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=100)


class Book(ormar.Model):
    class Meta(BaseMeta):
        tablename = "books"

    id: int = ormar.Integer(primary_key=True)
    author: Optional[Author] = ormar.ForeignKey(Author)
    title: str = ormar.String(max_length=100)
    year: int = ormar.Integer(nullable=True)


@pytest.fixture(autouse=True, scope="module")
def create_test_database():
    engine = sqlalchemy.create_engine(DATABASE_URL)
    metadata.drop_all(engine)
    metadata.create_all(engine)
    yield
    metadata.drop_all(engine)


@pytest.mark.asyncio
async def test_or_filters():
    async with database:
        tolkien = await Author(name="J.R.R. Tolkien").save()
        await Book(author=tolkien, title="The Hobbit", year=1933).save()
        await Book(author=tolkien, title="The Lord of the Rings", year=1955).save()
        await Book(author=tolkien, title="The Silmarillion", year=1977).save()
        sapkowski = await Author(name="Andrzej Sapkowski").save()
        await Book(author=sapkowski, title="The Witcher", year=1990).save()
        await Book(author=sapkowski, title="The Tower of Fools", year=2002).save()

        books = (
            await Book.objects.select_related("author")
            .filter(ormar.or_(author__name="J.R.R. Tolkien", year__gt=1970))
            .all()
        )
        assert len(books) == 5

        books = (
            await Book.objects.select_related("author")
            .filter(ormar.or_(author__name="J.R.R. Tolkien", year__lt=1995))
            .all()
        )
        assert len(books) == 4
        assert not any([x.title == "The Tower of Fools" for x in books])

        books = (
            await Book.objects.select_related("author")
            .filter(ormar.or_(year__gt=1960, year__lt=1940))
            .filter(author__name="J.R.R. Tolkien")
            .all()
        )
        assert len(books) == 2
        assert books[0].title == "The Hobbit"
        assert books[1].title == "The Silmarillion"

        books = (
            await Book.objects.select_related("author")
            .filter(
                ormar.or_(
                    ormar.and_(year__gt=1960, author__name="J.R.R. Tolkien"),
                    ormar.and_(year__lt=2000, author__name="Andrzej Sapkowski"),
                )
            )
            .filter(title__startswith="The")
            .all()
        )
        assert len(books) == 2
        assert books[0].title == "The Silmarillion"
        assert books[1].title == "The Witcher"

        books = (
            await Book.objects.select_related("author")
            .exclude(
                ormar.or_(
                    ormar.and_(year__gt=1960, author__name="J.R.R. Tolkien"),
                    ormar.and_(year__lt=2000, author__name="Andrzej Sapkowski"),
                )
            )
            .filter(title__startswith="The")
            .all()
        )
        assert len(books) == 3
        assert not any([x.title in ["The Silmarillion", "The Witcher"] for x in books])


# TODO: Check / modify
# process and and or into filter groups (V)
# check exclude queries working (V)

# when limit and no sql do not allow main model and other models
# check complex prefixes properly resolved
# fix types for FilterAction and FilterGroup (?)