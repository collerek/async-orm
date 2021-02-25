from typing import Any, TYPE_CHECKING

import databases
import pytest
import sqlalchemy
from pydantic.typing import ForwardRef

import ormar
from tests.settings import DATABASE_URL

database = databases.Database(DATABASE_URL, force_rollback=True)
metadata = sqlalchemy.MetaData()


class BaseMeta(ormar.ModelMeta):
    database = database
    metadata = metadata


class Category(ormar.Model):
    class Meta(BaseMeta):
        tablename = "categories"

    id = ormar.Integer(primary_key=True)
    name = ormar.String(max_length=40)


class PostCategory(ormar.Model):
    class Meta(BaseMeta):
        tablename = "posts_x_categories"

    id: int = ormar.Integer(primary_key=True)
    sort_order: int = ormar.Integer(nullable=True)
    param_name: str = ormar.String(default="Name", max_length=200)


class Blog(ormar.Model):
    class Meta(BaseMeta):
        pass

    id: int = ormar.Integer(primary_key=True)
    title: str = ormar.String(max_length=200)


class Post(ormar.Model):
    class Meta(BaseMeta):
        pass

    id: int = ormar.Integer(primary_key=True)
    title: str = ormar.String(max_length=200)
    categories = ormar.ManyToMany(Category, through=PostCategory)
    blog = ormar.ForeignKey(Blog)


@pytest.fixture(autouse=True, scope="module")
def create_test_database():
    engine = sqlalchemy.create_engine(DATABASE_URL)
    metadata.drop_all(engine)
    metadata.create_all(engine)
    yield
    metadata.drop_all(engine)


class PostCategory2(ormar.Model):
    class Meta(BaseMeta):
        tablename = "posts_x_categories2"

    id: int = ormar.Integer(primary_key=True)
    sort_order: int = ormar.Integer(nullable=True)


class Post2(ormar.Model):
    class Meta(BaseMeta):
        pass

    id: int = ormar.Integer(primary_key=True)
    title: str = ormar.String(max_length=200)
    categories = ormar.ManyToMany(Category, through=ForwardRef("PostCategory2"))


@pytest.mark.asyncio
async def test_forward_ref_is_updated():
    async with database:
        assert Post2.Meta.requires_ref_update
        Post2.update_forward_refs()

        assert Post2.Meta.model_fields["postcategory2"].to == PostCategory2


@pytest.mark.asyncio
async def test_setting_fields_on_through_model():
    async with database:
        post = await Post(title="Test post").save()
        category = await Category(name="Test category").save()
        await post.categories.add(category)

        assert hasattr(post.categories[0], "postcategory")
        assert post.categories[0].postcategory is None


@pytest.mark.asyncio
async def test_setting_additional_fields_on_through_model_in_add():
    async with database:
        post = await Post(title="Test post").save()
        category = await Category(name="Test category").save()
        await post.categories.add(category, sort_order=1)
        postcat = await PostCategory.objects.get()
        assert postcat.sort_order == 1


@pytest.mark.asyncio
async def test_setting_additional_fields_on_through_model_in_create():
    async with database:
        post = await Post(title="Test post").save()
        await post.categories.create(
            name="Test category2", postcategory={"sort_order": 2}
        )
        postcat = await PostCategory.objects.get()
        assert postcat.sort_order == 2


@pytest.mark.asyncio
async def test_getting_additional_fields_from_queryset() -> Any:
    async with database:
        post = await Post(title="Test post").save()
        await post.categories.create(
            name="Test category1", postcategory={"sort_order": 1}
        )
        await post.categories.create(
            name="Test category2", postcategory={"sort_order": 2}
        )

        await post.categories.all()
        assert post.categories[0].postcategory.sort_order == 1
        assert post.categories[1].postcategory.sort_order == 2

        post2 = await Post.objects.select_related("categories").get(
            categories__name="Test category2"
        )
        assert post2.categories[0].postcategory.sort_order == 2
        # if TYPE_CHECKING:
        #     reveal_type(post2)


@pytest.mark.asyncio
async def test_filtering_by_through_model() -> Any:
    async with database:
        post = await Post(title="Test post").save()
        await post.categories.create(
            name="Test category1",
            postcategory={"sort_order": 1, "param_name": "volume"},
        )
        await post.categories.create(
            name="Test category2", postcategory={"sort_order": 2, "param_name": "area"}
        )

        post2 = (
            await Post.objects.select_related("categories")
            .filter(postcategory__sort_order__gt=1)
            .get()
        )
        assert len(post2.categories) == 1
        assert post2.categories[0].postcategory.sort_order == 2

        post3 = await Post.objects.filter(
            categories__postcategory__param_name="volume"
        ).get()
        assert len(post3.categories) == 1
        assert post3.categories[0].postcategory.param_name == "volume"


@pytest.mark.asyncio
async def test_deep_filtering_by_through_model() -> Any:
    async with database:
        blog = await Blog(title="My Blog").save()
        post = await Post(title="Test post", blog=blog).save()

        await post.categories.create(
            name="Test category1",
            postcategory={"sort_order": 1, "param_name": "volume"},
        )
        await post.categories.create(
            name="Test category2", postcategory={"sort_order": 2, "param_name": "area"}
        )

        blog2 = (
            await Blog.objects.select_related("posts__categories")
            .filter(posts__postcategory__sort_order__gt=1)
            .get()
        )
        assert len(blog2.posts) == 1
        assert len(blog2.posts[0].categories) == 1
        assert blog2.posts[0].categories[0].postcategory.sort_order == 2

        blog3 = await Blog.objects.filter(
            posts__categories__postcategory__param_name="volume"
        ).get()
        assert len(blog3.posts) == 1
        assert len(blog3.posts[0].categories) == 1
        assert blog3.posts[0].categories[0].postcategory.param_name == "volume"


@pytest.mark.asyncio
async def test_ordering_by_through_model() -> Any:
    async with database:
        post = await Post(title="Test post").save()
        await post.categories.create(
            name="Test category1",
            postcategory={"sort_order": 2, "param_name": "volume"},
        )
        await post.categories.create(
            name="Test category2", postcategory={"sort_order": 1, "param_name": "area"}
        )
        await post.categories.create(
            name="Test category3",
            postcategory={"sort_order": 3, "param_name": "velocity"},
        )

        post2 = (
            await Post.objects.select_related("categories")
            .order_by("-postcategory__sort_order")
            .get()
        )
        assert len(post2.categories) == 3
        assert post2.categories[0].name == "Test category3"
        assert post2.categories[2].name == "Test category2"

        post3 = (
            await Post.objects.select_related("categories")
            .order_by("categories__postcategory__param_name")
            .get()
        )
        assert len(post3.categories) == 3
        assert post3.categories[0].postcategory.param_name == "area"
        assert post3.categories[2].postcategory.param_name == "volume"


# TODO: check/ modify following

# add to fields with class lower name (V)
# forward refs update (V)
# creating while adding to relation (kwargs in add) (V)
# creating in queryset proxy (dict with through name and kwargs) (V)
# loading the data into model instance of though model (V) <- fix fields ane exclude
# accessing from instance (V) <- no both sides only nested one is relevant, fix one side
# filtering in filter (through name normally) (V) < - table prefix from normal relation,
#               check if is_through needed, resolved side of relation
# ordering by in order_by


# updating in query
# modifying from instance (both sides?)
# including/excluding in fields?
# allowing to change fk fields names in through model?
# make through optional? auto-generated for cases other fields are missing?