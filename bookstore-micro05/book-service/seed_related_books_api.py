import json
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "http://localhost:8003/api"


def http_json(method: str, url: str, payload=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
        if not body:
            return None
        return json.loads(body)


def get_json(url: str):
    try:
        return http_json("GET", url)
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            return None
        raise


def ensure_categories(category_defs):
    existing = get_json(f"{BASE_URL}/categories/") or []
    by_name = {str(item.get("name", "")).strip().lower(): item for item in existing}

    out = {}
    for cat in category_defs:
        key = cat["name"].strip().lower()
        if key in by_name:
            out[cat["name"]] = int(by_name[key]["id"])
            continue

        created = http_json("POST", f"{BASE_URL}/categories/", cat)
        out[cat["name"]] = int(created["id"])
    return out


def seed_books(books, category_map):
    all_books = get_json(f"{BASE_URL}/books/") or []
    existing_key = {
        (str(item.get("title", "")).strip().lower(), str(item.get("author", "")).strip().lower())
        for item in all_books
    }

    created_count = 0
    skipped_count = 0

    for book in books:
        key = (book["title"].strip().lower(), book["author"].strip().lower())
        if key in existing_key:
            skipped_count += 1
            continue

        payload = {
            "title": book["title"],
            "author": book["author"],
            "price": book["price"],
            "stock": book["stock"],
            "description": book["description"],
            "category_id": category_map[book["category"]],
            "image_url": book.get("image_url"),
        }
        http_json("POST", f"{BASE_URL}/books/", payload)
        existing_key.add(key)
        created_count += 1

    return created_count, skipped_count


def main():
    categories = [
        {"name": "Manga", "description": "Truyen tranh Nhat Ban, gom cac series lien quan theo franchise."},
        {"name": "Light Novel", "description": "Tieu thuyet nhe va spin-off anime/manga."},
        {"name": "Shonen", "description": "Cac bo truyen hanh dong, phieu luu danh cho tuoi teen."},
        {"name": "Fantasy", "description": "Tac pham gia tuong, ma thuat, the gioi mo rong."},
        {"name": "Cong nghe", "description": "Sach lap trinh, thiet ke phan mem va ky thuat code."},
    ]

    books = [
        {
            "title": "Naruto Tap 1",
            "author": "Masashi Kishimoto",
            "category": "Manga",
            "price": "49000.00",
            "stock": 120,
            "description": "Khoi dau hanh trinh cua Naruto Uzumaki tai Lang La, lien quan truc tiep den Boruto.",
        },
        {
            "title": "Naruto Tap 27",
            "author": "Masashi Kishimoto",
            "category": "Manga",
            "price": "52000.00",
            "stock": 90,
            "description": "Arc Shippuden voi Sakura, Sasuke va Akatsuki, cung vu tru voi Boruto.",
        },
        {
            "title": "Naruto Tap 72 - Ket Thuc",
            "author": "Masashi Kishimoto",
            "category": "Manga",
            "price": "59000.00",
            "stock": 70,
            "description": "Tap cuoi cua Naruto, boi canh truoc thoi ky Boruto.",
        },
        {
            "title": "Boruto Tap 1",
            "author": "Ukyo Kodachi",
            "category": "Manga",
            "price": "52000.00",
            "stock": 140,
            "description": "Phan tiep noi cua Naruto, theo chan Boruto Uzumaki the he moi.",
        },
        {
            "title": "Boruto Tap 10",
            "author": "Masashi Kishimoto",
            "category": "Manga",
            "price": "55000.00",
            "stock": 100,
            "description": "Dien bien moi trong vu tru ninja, lien quan nhan vat Naruto va Sasuke.",
        },
        {
            "title": "Boruto: Two Blue Vortex Tap 1",
            "author": "Masashi Kishimoto",
            "category": "Manga",
            "price": "65000.00",
            "stock": 80,
            "description": "Phan moi cua Boruto sau timeskip, ket noi truc tiep voi Boruto truoc do.",
        },
        {
            "title": "Naruto Hiden: Kakashi Retsuden",
            "author": "Jun Esaka",
            "category": "Light Novel",
            "price": "89000.00",
            "stock": 40,
            "description": "Light novel ngoai truyen Naruto, bo sung boi canh nhan vat cho fan Boruto.",
        },
        {
            "title": "One Piece Tap 1",
            "author": "Eiichiro Oda",
            "category": "Shonen",
            "price": "52000.00",
            "stock": 160,
            "description": "Khoi dau hanh trinh cua Luffy, cung franchise voi cac tap One Piece khac.",
        },
        {
            "title": "One Piece Tap 60",
            "author": "Eiichiro Oda",
            "category": "Shonen",
            "price": "57000.00",
            "stock": 110,
            "description": "Arc Marineford day cam xuc, lien quan den cau chuyen tong the One Piece.",
        },
        {
            "title": "One Piece Tap 100",
            "author": "Eiichiro Oda",
            "category": "Shonen",
            "price": "69000.00",
            "stock": 85,
            "description": "Wano arc, tiep noi hanh trinh cua Bang Mu Rom trong One Piece.",
        },
        {
            "title": "One Piece Film Red Novel",
            "author": "Jun Esaka",
            "category": "Light Novel",
            "price": "99000.00",
            "stock": 35,
            "description": "Ban novel lien quan den One Piece Film Red, ket noi fan One Piece.",
        },
        {
            "title": "Dragon Ball Tap 1",
            "author": "Akira Toriyama",
            "category": "Manga",
            "price": "50000.00",
            "stock": 100,
            "description": "Khong dau huyen thoai Goku, cung franchise voi Dragon Ball Super.",
        },
        {
            "title": "Dragon Ball Super Tap 1",
            "author": "Toyotaro",
            "category": "Manga",
            "price": "54000.00",
            "stock": 90,
            "description": "Phan tiep noi Dragon Ball Z, lien quan truc tiep Dragon Ball co dien.",
        },
        {
            "title": "Dragon Ball Super Tap 20",
            "author": "Toyotaro",
            "category": "Manga",
            "price": "59000.00",
            "stock": 65,
            "description": "Tien trinh moi trong Dragon Ball Super, phu hop nguoi doc da biet Dragon Ball.",
        },
        {
            "title": "Jujutsu Kaisen Tap 1",
            "author": "Gege Akutami",
            "category": "Shonen",
            "price": "53000.00",
            "stock": 130,
            "description": "Mo dau the gioi chu thuat, lien quan den cac tap Jujutsu Kaisen tiep theo.",
        },
        {
            "title": "Jujutsu Kaisen Tap 15",
            "author": "Gege Akutami",
            "category": "Shonen",
            "price": "56000.00",
            "stock": 90,
            "description": "Dien bien lon trong Jujutsu Kaisen, giai doan Shibuya day kich tinh.",
        },
        {
            "title": "Jujutsu Kaisen Tap 24",
            "author": "Gege Akutami",
            "category": "Shonen",
            "price": "62000.00",
            "stock": 70,
            "description": "Tap moi Jujutsu Kaisen voi nhieu nut that quan trong.",
        },
        {
            "title": "Kimetsu no Yaiba Tap 1",
            "author": "Koyoharu Gotouge",
            "category": "Manga",
            "price": "52000.00",
            "stock": 120,
            "description": "Mo dau hanh trinh cua Tanjiro, lien quan cac tap Kimetsu tiep theo.",
        },
        {
            "title": "Kimetsu no Yaiba Tap 23",
            "author": "Koyoharu Gotouge",
            "category": "Manga",
            "price": "64000.00",
            "stock": 75,
            "description": "Tap ket Kimetsu no Yaiba, hoan tat mach truyen cua franchise.",
        },
        {
            "title": "Attack on Titan Tap 1",
            "author": "Hajime Isayama",
            "category": "Manga",
            "price": "53000.00",
            "stock": 85,
            "description": "Khoi dau Attack on Titan, lien quan den cac tap final season.",
        },
        {
            "title": "Attack on Titan Tap 34",
            "author": "Hajime Isayama",
            "category": "Manga",
            "price": "68000.00",
            "stock": 60,
            "description": "Tap cuoi Attack on Titan, dong mach truyen voi cac tap truoc.",
        },
        {
            "title": "Bleach Tap 1",
            "author": "Tite Kubo",
            "category": "Shonen",
            "price": "51000.00",
            "stock": 70,
            "description": "Mo dau Bleach, lien quan arc Soul Society va Thousand-Year Blood War.",
        },
        {
            "title": "Bleach Tap 74",
            "author": "Tite Kubo",
            "category": "Shonen",
            "price": "66000.00",
            "stock": 45,
            "description": "Tap ket Bleach, ket noi voi anime Thousand-Year Blood War.",
        },
        {
            "title": "My Hero Academia Tap 1",
            "author": "Kohei Horikoshi",
            "category": "Shonen",
            "price": "52000.00",
            "stock": 120,
            "description": "Khoi dau hanh trinh cua Midoriya, cung franchise voi cac tap MHA.",
        },
        {
            "title": "My Hero Academia Tap 39",
            "author": "Kohei Horikoshi",
            "category": "Shonen",
            "price": "62000.00",
            "stock": 80,
            "description": "Tap gan cuoi MHA, mach truyen lien thong cho fan da theo doi bo nay.",
        },
        {
            "title": "Spy x Family Tap 1",
            "author": "Tatsuya Endo",
            "category": "Manga",
            "price": "52000.00",
            "stock": 100,
            "description": "Gia dinh Forger bat dau su menh, lien quan truc tiep cac tap tiep theo.",
        },
        {
            "title": "Spy x Family Tap 12",
            "author": "Tatsuya Endo",
            "category": "Manga",
            "price": "59000.00",
            "stock": 65,
            "description": "Tap moi cua Spy x Family, phu hop nguoi da doc cac tap dau.",
        },
        {
            "title": "Haikyuu!! Tap 1",
            "author": "Haruichi Furudate",
            "category": "Shonen",
            "price": "50000.00",
            "stock": 90,
            "description": "Bat dau hanh trinh bong chuyen cua Karasuno, lien quan cac tap sau.",
        },
        {
            "title": "Haikyuu!! Tap 45",
            "author": "Haruichi Furudate",
            "category": "Shonen",
            "price": "65000.00",
            "stock": 55,
            "description": "Tap cuoi Haikyuu, hoan thien hanh trinh cua cac nhan vat.",
        },
        {
            "title": "Clean Architecture",
            "author": "Robert C. Martin",
            "category": "Cong nghe",
            "price": "179000.00",
            "stock": 60,
            "description": "Sach cung tac gia voi Clean Code, tap trung vao kien truc he thong ben vung.",
        },
        {
            "title": "The Pragmatic Programmer",
            "author": "Andrew Hunt",
            "category": "Cong nghe",
            "price": "189000.00",
            "stock": 55,
            "description": "Bo nguyen tac thuc chien cho lap trinh vien, rat lien quan voi tu duy trong Clean Code.",
        },
        {
            "title": "Refactoring",
            "author": "Martin Fowler",
            "category": "Cong nghe",
            "price": "199000.00",
            "stock": 50,
            "description": "Huong dan cai tien ma nguon va cau truc code, phu hop nguoi doc Clean Code.",
        },
        {
            "title": "Design Patterns",
            "author": "Erich Gamma",
            "category": "Cong nghe",
            "price": "219000.00",
            "stock": 40,
            "description": "Mau thiet ke kinh dien trong OOP, bo sung cho nang luc clean architecture va clean code.",
        },
        {
            "title": "Working Effectively with Legacy Code",
            "author": "Michael Feathers",
            "category": "Cong nghe",
            "price": "205000.00",
            "stock": 35,
            "description": "Ky thuat xu ly he thong cu, ket hop tot voi Refactoring va Clean Code.",
        },
        {
            "title": "The Hobbit",
            "author": "J.R.R. Tolkien",
            "category": "Fantasy",
            "price": "129000.00",
            "stock": 70,
            "description": "Tien truyen trong vu tru Middle-earth, lien quan truc tiep The Lord of the Rings.",
        },
        {
            "title": "The Fellowship of the Ring",
            "author": "J.R.R. Tolkien",
            "category": "Fantasy",
            "price": "159000.00",
            "stock": 60,
            "description": "Phan 1 Lord of the Rings, lien thong boi canh voi The Hobbit.",
        },
        {
            "title": "The Two Towers",
            "author": "J.R.R. Tolkien",
            "category": "Fantasy",
            "price": "159000.00",
            "stock": 55,
            "description": "Phan 2 Lord of the Rings, tiep noi truc tiep Fellowship.",
        },
        {
            "title": "The Return of the King",
            "author": "J.R.R. Tolkien",
            "category": "Fantasy",
            "price": "169000.00",
            "stock": 50,
            "description": "Phan 3 Lord of the Rings, ket thuc bo ba kinh dien.",
        },
    ]

    category_map = ensure_categories(categories)
    created_count, skipped_count = seed_books(books, category_map)
    print(f"Seed completed. created={created_count}, skipped_existing={skipped_count}, total_input={len(books)}")


if __name__ == "__main__":
    main()
