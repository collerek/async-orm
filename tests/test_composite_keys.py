from typing import (
    List,
    Optional,
)
import uuid

import databases
import pytest
import sqlalchemy

import ormar
from tests.settings import DATABASE_URL

database = databases.Database(DATABASE_URL, force_rollback=True)
metadata = sqlalchemy.MetaData()


class User(ormar.Model):
    class Meta:
        tablename = "users"
        metadata = metadata
        database = database

    id: uuid.UUID = ormar.UUID(primary_key=True, default=uuid.uuid4)
    email: str = ormar.String(nullable=False, max_length=100)


class Project(ormar.Model):
    class Meta:
        tablename = "projects"
        metadata = metadata
        database = database
        constraints = [
            ormar.PrimaryKeyConstraint("id", "owner"),
            ormar.ForeignKeyConstraint(User, ["owner_id"], ["id"], "owner"),
        ]

    id: int = ormar.Integer()
    owner_id: uuid.UUID = ormar.UUID(default=uuid.uuid4)
    name: str = ormar.String(nullable=False, max_length=100)


class Tag(ormar.Model):
    class Meta:
        tablename = "tags"
        metadata = metadata
        database = database
        constraints = [
            ormar.PrimaryKeyConstraint("id", "owner", "project_id"),
            ormar.ForeignKeyConstraint(
                Project,
                ["owner", "project_id"],
                ["owner", "id"],
                name="tag_project",
            ),
        ]

    id: int = ormar.Integer(primary_key=True)
    owner: User = ormar.ForeignKey(User)
    project_id: int = ormar.Integer()
    name: str = ormar.String(nullable=False, max_length=100)


class TaskTag(ormar.Model):
    class Meta:
        tablename = "task_tags"
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)
    assigned_by: Optional[User] = ormar.ForeignKey(User)


class Task(ormar.Model):
    class Meta:
        tablename = "tasks"
        metadata = metadata
        database = database
        constraints = [
            ormar.PrimaryKeyConstraint("id", "owner", "project"),
            ormar.ForeignKeyConstraint(
                User,
                ["user_id"],
                ["id"],
                name="owner",
                related_name="owners",
                db_name="owner_fk",
            ),
            ormar.ForeignKeyConstraint(
                Project,
                ["owner_id", "project_id"],
                ["owner", "id"],
            ),
        ]

    id: int = ormar.Integer(primary_key=True)
    owner_id: uuid.UUID = ormar.UUID()
    project_id: int = ormar.Integer()
    description: str = ormar.String(nullable=False, max_length=200)
    completed: bool = ormar.Boolean(nullable=False, default=False)
    tags: Optional[List[Tag]] = ormar.ManyToMany(Tag, through=TaskTag)


@pytest.fixture(autouse=True, scope="module")
def create_test_database():
    engine = sqlalchemy.create_engine(DATABASE_URL)
    metadata.drop_all(engine)
    metadata.create_all(engine)
    yield
    metadata.drop_all(engine)


################
# PK tests
################


@pytest.mark.asyncio
async def test_composite_pk_crud():
    async with database:
        async with database.transaction(force_rollback=True):
            user_beth = User(email="beth@example.com")
            await user_beth.save()
            project_bedroom = await Project.objects.create(
                owner=user_beth, name="Clean up the bedroom"
            )

            tag_urgent = Tag(tag_project=project_bedroom, name="URGENT!")
            tag_medium = Tag(
                owner=user_beth,
                tag_project=project_bedroom,
                name="Fine if mum can't smell it",
            )
            await tag_urgent.save()
            await tag_medium.save()

            task_underwear = Task(
                project=project_bedroom,
                description="Collect underwear",
                completed=False,
                tags=[tag_medium],
            )
            task_monster = Task(
                owner=user_beth,
                project=project_bedroom,
                description="Feed the monster under the bed",
                completed=False,
                tags=[tag_urgent],
            )
            await task_underwear.save()
            await task_monster.save()

            task = await Task.objects.get(description="Collect underwear")
            assert task.pk == task_underwear.pk
            assert isinstance(task.project, ormar.Model)
            assert task.project.description == "Clean up the bedroom"
            await task.project.load()
            task.project.name = "Make bedroom appear clean"
            await task.project.save()
            project = await Project.objects.get(name="Make bedroom appear clean")
            assert project.pk == project_bedroom.pk
            assert isinstance(project, ormar.Model)

            assert task.tags is not None and len(task.tags) == 1
            await task.tags[0].delete()
            all_tags = await Tag.objects.all()
            assert len(all_tags) == 1
            assert all_tags[0].project.owner.email == "beth@example.com"


@pytest.mark.asyncio
async def test_error_multiple_pk_declarations():
    with pytest.raises(ormar.ModelDefinitionError):

        class MultiPk(ormar.Model):
            class Meta:
                database = database
                metadata = metadata
                constraints = [
                    ormar.PrimaryKeyConstraint("id_1"),
                ]

            id_1: int = ormar.Integer()
            id_2: int = ormar.Integer(primary_key=True)


@pytest.mark.asyncio
async def test_error_mixed_pk_declarations():
    with pytest.raises(ormar.ModelDefinitionError):

        class MixedPk(ormar.Model):
            class Meta:
                constraints = [
                    ormar.PrimaryKeyConstraint("id_1", "id_2"),
                ]

            id_1: int = ormar.Integer()
            id_2: int = ormar.Integer(primary_key=True)


@pytest.mark.asyncio
async def test_error_pk_using_fk_column_directly():
    """
    In order to prevent direct access to fk columns, we need to disallow
    pk declarations that use columns that are part of an fk directly.
    Otherwise the fk columns would become directly accessible through
    model.pk.
    Instead, pk declarations should use the corresponding fk relations.
    """
    with pytest.raises(ormar.ModelDefinitionError):

        class DirectPk(ormar.Model):
            class Meta:
                constraints = [
                    ormar.PrimaryKeyConstraint("id", "user_id"),
                    ormar.ForeignKeyConstraint(User, ["user_id"], ["id"]),
                ]

            id: int = ormar.Integer()
            user_id: uuid.UUID = ormar.UUID(default=uuid.uuid4)


@pytest.mark.asyncio
async def test_error_when_setting_part_of_pk_none():
    async with database:
        async with database.transaction(force_rollback=True):
            user = User(email="tom@example.com")
            await user.save()
            project = Project(owner=user, name="Doom impending")
            await project.save()

            with pytest.raises(ValueError):
                project.owner = None


################
# FK tests
################


@pytest.mark.asyncio
async def test_init_fk_column_directly_fails():
    async with database:
        async with database.transaction(force_rollback=True):
            user = User(email="tom@example.com")
            await user.save()

            with pytest.raises(ValueError):
                Project(owner_id=user.id, name="A failed endeavour")


@pytest.mark.asyncio
async def test_set_fk_column_directly_fails():
    async with database:
        async with database.transaction(force_rollback=True):
            user_1 = User(email="tim@example.com")
            user_2 = User(email="tam@example.com")
            await user_1.save()
            await user_2.save()
            project = Project(owner=user_1, name="So far so good")
            await project.save()

            with pytest.raises(ValueError):
                project.owner_id = user_2.id


@pytest.mark.asyncio
async def test_get_fk_column_directly_fails():
    async with database:
        async with database.transaction(force_rollback=True):
            user = User(email="tom@example.com")
            await user.save()
            project = Project(owner=user, name="Doom impending")
            await project.save()

            with pytest.raises(ValueError):
                project.owner_id


@pytest.mark.asyncio
async def test_define_fk_field_to_composite_pk_model_fails():
    """
    Defining a FK to a model with composite PK would implicitly create
    multiple columns to store the key and we want to prevent this
    implicit behaviour. Instead, a ForeignKeyConstraint should be used.
    """
    async with database:
        with pytest.raises(ormar.ModelDefinitionError):

            class ProjectStatus(ormar.Model):
                class Meta:
                    tablename = "project_states"
                    metadata = metadata
                    database = database

                id: int = ormar.Integer(primary_key=True)
                project: Optional[Project] = ormar.ForeignKey(Project)


@pytest.mark.asyncio
async def test_composite_fk_reverse_relation_created():
    async with database:
        async with database.transaction(force_rollback=True):
            user = User(email="tom@example.com")
            await user.save()
            project = Project(owner=user, name="Find inner peace")
            await project.save()
            task = Task(
                project=project,
                description="Meditate 25 hours a day",
                completed=True,
            )
            await task.save()

            assert len(project.tasks) == 1
            assert isinstance(project.tasks[0], ormar.Model)
            assert project.tasks[0].pk == task.pk


################
# Consistency with pydantic
################


@pytest.mark.asyncio
async def test_correct_pydantic_dict_with_composite_keys():
    async with database:
        async with database.transaction(force_rollback=True):
            user = User(email="juan@example.com")
            await user.save()
            project = Project(owner=user, name="Get rich fast")
            await project.save()
            task = Task(
                project=project,
                description="Buy lots of Bitcoin",
                completed=False,
            )
            await task.save()

            loaded_user = await User.objects.get(email="juan@example.com")
            await loaded_user.load_all(follow=True)
            expected_user_dict = {
                "id": user.id,
                "email": user.email,
            }
            assert loaded_user.dict() == expected_user_dict

            assert len(loaded_user.projects) == 1
            loaded_project = loaded_user.projects[0]
            expected_project_dict = {
                "id": project.id,
                "name": project.name,
                "owner": expected_user_dict,
            }
            assert loaded_project.dict() == expected_project_dict

            assert len(loaded_project.tasks) == 1
            loaded_task = loaded_project.tasks[0]
            assert loaded_task.dict() == {
                "id": task.id,
                "owner": expected_user_dict,
                "project": expected_project_dict,
                "description": task.description,
                "completed": task.completed,
                "tags": None,
            }


################
# pk property working correctly
################


@pytest.mark.asyncio
async def test_scalar_pk_property():
    async with database:
        async with database.transaction(force_rollback=True):
            user = await User.objects.create(email="torben@example.com")
            assert isinstance(user.pk, uuid.UUID)
            assert user.pk == user.id


@pytest.mark.asyncio
async def test_get_composite_pk_property():
    async with database:
        async with database.transaction(force_rollback=True):
            user = await User.objects.create(email="ai@example.com")

            project = await Project.objects.create(
                owner=user,
                name="Gardening",
            )
            assert isinstance(project.pk, dict)
            assert len(project.pk) == 2
            assert set(project.pk.keys()) == {"id", "owner"}
            assert project.pk["owner"] == user

            task = await Task.objects.create(
                project=project,
                description="Down with the weeds!",
                completed=False,
            )
            assert isinstance(task.pk, dict)
            assert len(task.pk) == 3
            assert set(task.pk.keys()) == {"id", "owner", "project"}
            assert task.pk["owner"] == user.id
            assert task.pk["project"] == project.pk["id"]


@pytest.mark.asyncio
async def test_set_composite_pk_property():
    async with database:
        async with database.transaction(force_rollback=True):
            user_tian = await User(email="tian@example.com").save()
            user_josie = await User(email="josie@example.com").save()

            project = await Project(
                owner=user_tian,
                name="Become an influencer",
            ).save()
            project.pk = {"id": 4, "owner": user_josie}
            assert project.id == 4
            assert project.owner == user_josie
            await project.update()
