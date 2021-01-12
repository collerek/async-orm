# type: ignore
import databases
import pytest
import sqlalchemy
import sqlalchemy as sa
from pydantic.typing import ForwardRef
from sqlalchemy import create_engine

import ormar
from ormar import ModelMeta
from ormar.exceptions import ModelError
from tests.settings import DATABASE_URL

metadata = sa.MetaData()
db = databases.Database(DATABASE_URL)
engine = create_engine(DATABASE_URL)

Person = ForwardRef("Person")


class Person(ormar.Model):
    class Meta(ModelMeta):
        metadata = metadata
        database = db

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=100)
    supervisor: Person = ormar.ForeignKey(Person, related_name="employees")


Person.update_forward_refs()

Game = ForwardRef("Game")
Child = ForwardRef("Child")


class ChildFriend(ormar.Model):
    class Meta(ModelMeta):
        metadata = metadata
        database = db


class Child(ormar.Model):
    class Meta(ModelMeta):
        metadata = metadata
        database = db

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=100)
    favourite_game: Game = ormar.ForeignKey(Game, related_name="liked_by")
    least_favourite_game: Game = ormar.ForeignKey(Game, related_name="not_liked_by")
    friends = ormar.ManyToMany(Child, through=ChildFriend, related_name="also_friends")


class Game(ormar.Model):
    class Meta(ModelMeta):
        metadata = metadata
        database = db

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=100)


Child.update_forward_refs()


@pytest.fixture(autouse=True, scope="module")
def create_test_database():
    metadata.create_all(engine)
    yield
    metadata.drop_all(engine)


@pytest.fixture(scope="function")
async def cleanup():
    yield
    async with db:
        await ChildFriend.objects.delete(each=True)
        await Child.objects.delete(each=True)
        await Game.objects.delete(each=True)
        await Person.objects.delete(each=True)


@pytest.mark.asyncio
async def test_not_uprated_model_raises_errors():
    Person2 = ForwardRef("Person2")

    class Person2(ormar.Model):
        class Meta(ModelMeta):
            metadata = metadata
            database = db

        id: int = ormar.Integer(primary_key=True)
        name: str = ormar.String(max_length=100)
        supervisor: Person2 = ormar.ForeignKey(Person2, related_name="employees")

    with pytest.raises(ModelError):
        await Person2.objects.create(name="Test")

    with pytest.raises(ModelError):
        Person2(name="Test")

    with pytest.raises(ModelError):
        await Person2.objects.get()


def test_proper_field_init():
    assert "supervisor" in Person.Meta.model_fields
    assert Person.Meta.model_fields["supervisor"].to == Person

    assert "supervisor" in Person.__fields__
    assert Person.__fields__["supervisor"].type_ == Person

    assert "supervisor" in Person.Meta.table.columns
    assert isinstance(
        Person.Meta.table.columns["supervisor"].type, sqlalchemy.sql.sqltypes.Integer
    )
    assert len(Person.Meta.table.columns["supervisor"].foreign_keys) > 0

    assert "person_supervisor" in Person.Meta.alias_manager._aliases_new


@pytest.mark.asyncio
async def test_self_relation():
    async with db:
        async with db.transaction(force_rollback=True):
            sam = await Person.objects.create(name="Sam")
            joe = await Person(name="Joe", supervisor=sam).save()
            assert joe.supervisor.name == "Sam"

            joe_check = await Person.objects.select_related("supervisor").get(
                name="Joe"
            )
            assert joe_check.supervisor.name == "Sam"

            sam_check = await Person.objects.select_related("employees").get(name="Sam")
            assert sam_check.name == "Sam"
            assert sam_check.employees[0].name == "Joe"


@pytest.mark.asyncio
async def test_other_forwardref_relation(cleanup):
    async with db:
        async with db.transaction(force_rollback=True):
            checkers = await Game.objects.create(name="checkers")
            uno = await Game(name="Uno").save()

            await Child(
                name="Billy", favourite_game=uno, least_favourite_game=checkers
            ).save()
            await Child(
                name="Kate", favourite_game=checkers, least_favourite_game=uno
            ).save()

            billy_check = await Child.objects.select_related(
                ["favourite_game", "least_favourite_game"]
            ).get(name="Billy")
            assert billy_check.favourite_game == uno
            assert billy_check.least_favourite_game == checkers

            uno_check = await Game.objects.select_related(
                ["liked_by", "not_liked_by"]
            ).get(name="Uno")
            assert uno_check.liked_by[0].name == "Billy"
            assert uno_check.not_liked_by[0].name == "Kate"


@pytest.mark.asyncio
async def test_m2m_self_forwardref_relation(cleanup):
    async with db:
        async with db.transaction(force_rollback=True):
            checkers = await Game.objects.create(name="checkers")
            uno = await Game(name="Uno").save()
            jenga = await Game(name="Jenga").save()

            billy = await Child(
                name="Billy", favourite_game=uno, least_favourite_game=checkers
            ).save()
            kate = await Child(
                name="Kate", favourite_game=checkers, least_favourite_game=uno
            ).save()
            steve = await Child(
                name="Steve", favourite_game=jenga, least_favourite_game=uno
            ).save()

            await billy.friends.add(kate)
            await billy.friends.add(steve)

            # await steve.friends.add(kate)
            # await steve.friends.add(billy)

            billy_check = await Child.objects.select_related(
                ["friends", "favourite_game", "least_favourite_game",]
            ).get(name="Billy")
            assert len(billy_check.friends) == 2
            assert billy_check.friends[0].name == "Kate"
            assert billy_check.friends[1].name == "Steve"
            assert billy_check.favourite_game.name == "Uno"

            kate_check = await Child.objects.select_related(["also_friends",]).get(
                name="Kate"
            )
            assert len(kate_check.also_friends) == 1
            assert kate_check.also_friends[0].name == "Billy"