from sqladmin import ModelView
from db.models import Hotel, Station, User, HotelState, ScreenSession, CustomBlock

class HotelAdmin(ModelView, model=Hotel):
    column_list = [Hotel.id, Hotel.name, Hotel.slug, Hotel.is_active]
    name = "Отель"
    name_plural = "Отели"
    icon = "fa-solid fa-hotel"

class StationAdmin(ModelView, model=Station):
    column_list = [Station.id, Station.title, Station.is_active]
    name = "Станция"
    name_plural = "Радиостанции"
    icon = "fa-solid fa-music"

class UserAdmin(ModelView, model=User):
    column_list = [User.telegram_id, User.full_name, User.role, User.hotel_id]
    name = "Сотрудник"
    name_plural = "Сотрудники"
    icon = "fa-solid fa-user"

class ScreenSessionAdmin(ModelView, model=ScreenSession):
    column_list = [ScreenSession.id, ScreenSession.pairing_code, ScreenSession.hotel_id, ScreenSession.created_at]
    name = "Сессия экрана"
    name_plural = "Экраны (ТВ)"
    icon = "fa-solid fa-tv"

class CustomBlockAdmin(ModelView, model=CustomBlock):
    column_list = [CustomBlock.id, CustomBlock.hotel_id, CustomBlock.position, CustomBlock.is_active]
    name = "Инфо-блок"
    name_plural = "Инфо-блоки"
    icon = "fa-solid fa-shapes"
    # Подсказка для тебя при заполнении:
    form_widget_args = {
        "position": {"placeholder": "top-left, top-center, bottom-center, center"}
    }