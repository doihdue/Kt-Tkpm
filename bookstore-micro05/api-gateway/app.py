import asyncio
import httpx
from typing import Optional, List
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Form, HTTPException, status, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="Bookstore UI Gateway")
app.add_middleware(SessionMiddleware, secret_key="s3cr3t_bookstore_session_key")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# --- Service URLs ---
# In a real production environment, these would come from environment variables.
CUSTOMER_SERVICE_URL = "http://customer-service:8000"
BOOK_SERVICE_URL = "http://book-service:8000"
CART_SERVICE_URL = "http://cart-service:8000"
ORDER_SERVICE_URL = "http://order-service:8000"
STAFF_SERVICE_URL = "http://staff-service:8000"
COMMENT_RATE_SERVICE_URL = "http://comment-rate-service:8000"
RECOMMENDER_AI_SERVICE_URL = "http://recommender-ai-service:8000"

# --- Data Layer ---
# Authentication is mocked because backend services lack password fields.
# This mock includes IDs to link to the actual services.


async def get_current_user(request: Request):
    user_session_data = request.session.get("user")
    if not user_session_data:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})

    user_id = user_session_data.get("id")
    user_role = user_session_data.get("role")
    
    service_url = ""
    api_path = ""
    if user_role == "customer":
        service_url = CUSTOMER_SERVICE_URL
        api_path = f"/api/customers/{user_id}/"
    elif user_role == "staff":
        service_url = STAFF_SERVICE_URL
        api_path = f"/api/staff/{user_id}/"
    else:
        request.session.pop("user", None)
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})

    try:
        async with httpx.AsyncClient(base_url=service_url) as client:
            response = await client.get(api_path)
            if response.status_code == 200:
                user_info = response.json()
                user_info['role'] = user_role
                user_info['username'] = user_session_data.get('username')
                return user_info
            else:
                request.session.pop("user", None)
                raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    except httpx.RequestError as e:
        print(f"Could not connect to service: {e}")
        raise HTTPException(status_code=503, detail="Dịch vụ người dùng không khả dụng.")


def role_required(user: dict, allowed: List[str]):
    if user["role"] not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền truy cập")


async def get_order_by_code(order_code: str):
    try:
        async with httpx.AsyncClient(base_url=ORDER_SERVICE_URL) as client:
            response = await client.get("/api/orders")
            response.raise_for_status()
            orders = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        raise HTTPException(status_code=503, detail=f"Lỗi dịch vụ đơn hàng: {e}")

    order = next((item for item in orders if item.get("order_code") == order_code), None)
    if not order:
        raise HTTPException(status_code=404, detail="Đơn hàng không tìm thấy")
    return order


async def fetch_home_sections(user: Optional[dict] = None):
    featured_books = []
    newest_books = []
    recommended_books = []

    async with httpx.AsyncClient() as client:
        all_books = []
        all_books_res = await client.get(f"{BOOK_SERVICE_URL}/api/books/")
        if all_books_res.status_code == 200:
            all_books_data = all_books_res.json()
            if isinstance(all_books_data, dict) and "results" in all_books_data:
                all_books = all_books_data["results"]
            else:
                all_books = all_books_data

        if all_books:
            newest_books = sorted(all_books, key=lambda b: b.get("id", 0), reverse=True)[:4]

            sold_by_book_id = {}
            try:
                orders_res = await client.get(f"{ORDER_SERVICE_URL}/api/orders")
                if orders_res.status_code == 200:
                    orders = orders_res.json()
                    for order in orders:
                        for item in order.get("items", []):
                            try:
                                book_id = int(item.get("book_id"))
                                qty = int(item.get("quantity", 0) or 0)
                            except (TypeError, ValueError):
                                continue
                            if qty > 0:
                                sold_by_book_id[book_id] = sold_by_book_id.get(book_id, 0) + qty
            except (httpx.RequestError, httpx.HTTPStatusError):
                sold_by_book_id = {}

            if sold_by_book_id:
                book_map = {b.get("id"): b for b in all_books if b.get("id") is not None}
                ranked_book_ids = sorted(sold_by_book_id.items(), key=lambda pair: pair[1], reverse=True)
                for book_id, sold_qty in ranked_book_ids:
                    book = book_map.get(book_id)
                    if not book:
                        continue
                    book_with_meta = dict(book)
                    book_with_meta["sold_quantity"] = sold_qty
                    featured_books.append(book_with_meta)
                    if len(featured_books) == 4:
                        break

            if not featured_books:
                featured_books = newest_books[:4]

            # Personalized recommendations from recommender-ai-service.
            if user and user.get("role") == "customer" and user.get("id"):
                try:
                    rec_res = await client.post(
                        f"{RECOMMENDER_AI_SERVICE_URL}/api/recommendations",
                        json={"customer_id": int(user.get("id")), "viewed_book_ids": []},
                    )
                    if rec_res.status_code == 200:
                        rec_items = rec_res.json()
                        rec_book_ids = [item.get("book_id") for item in rec_items if item.get("book_id") is not None]
                        rec_meta = {item.get("book_id"): item for item in rec_items if item.get("book_id") is not None}
                        book_map = {b.get("id"): b for b in all_books if b.get("id") is not None}
                        for rec_book_id in rec_book_ids:
                            book = book_map.get(rec_book_id)
                            if not book:
                                continue
                            book_with_reason = dict(book)
                            book_with_reason["recommend_reason"] = rec_meta.get(rec_book_id, {}).get("reason")
                            recommended_books.append(book_with_reason)
                except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
                    recommended_books = []

    return featured_books, newest_books, recommended_books


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user_session = request.session.get("user")
    if user_session:
        if user_session.get("role") == "staff":
            return RedirectResponse(url="/admin")

    user = user_session if user_session else None
    featured_books, newest_books, recommended_books = [], [], []
    try:
        featured_books, newest_books, recommended_books = await fetch_home_sections(user)
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass

    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "featured_books": featured_books,
        "newest_books": newest_books,
        "recommended_books": recommended_books,
    })


@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request, msg: Optional[str] = None):
    return templates.TemplateResponse("register.html", {"request": request, "msg": msg})


@app.post("/register", response_class=HTMLResponse)
async def register_post(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    phone_number: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...)
):
    if password != password2:
        return templates.TemplateResponse("register.html", {"request": request, "msg": "Mật khẩu xác nhận không khớp."})

    new_customer_payload = {
        "name": name,
        "username": username,
        "email": email,
        "phone_number": phone_number,
        "password": password
    }

    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            response = await client.post("/api/customers/", json=new_customer_payload)
            if response.status_code != 201:
                try:
                    error_data = response.json()
                    error_messages = []
                    # Xử lý các định dạng lỗi khác nhau (lỗi xác thực của DRF và các lỗi chuỗi đơn giản)
                    for field, messages in error_data.items():
                        if isinstance(messages, list):
                            # Dành cho lỗi như {"username": ["tên người dùng này đã tồn tại"]}
                            error_messages.append(f"{field.capitalize()}: {', '.join(messages)}")
                        else:
                            # Dành cho lỗi như {"error": "Dịch vụ không khả dụng"}
                            error_messages.append(str(messages))
                    error_detail = " ".join(error_messages) if error_messages else "Lỗi không xác định từ dịch vụ."
                except Exception:
                    error_detail = "Đã có lỗi xảy ra khi tạo tài khoản. Vui lòng thử lại."
                return templates.TemplateResponse("register.html", {"request": request, "msg": error_detail})

            # Automatically log in after successful registration
            login_payload = {"username": username, "password": password}
            # NOTE: This assumes a login endpoint like /api/auth/token/ exists on customer-service
            login_res = await client.post("/api/auth/token/", json=login_payload)
            
            if login_res.status_code == 200:
                user_data = login_res.json()
                request.session["user"] = {
                    "id": user_data.get("id"),
                    "username": user_data.get("username"),
                    "role": "customer"
                }
                return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
            else:
                return templates.TemplateResponse("login.html", {"request": request, "msg": "Đăng ký thành công. Vui lòng đăng nhập."})

    except (httpx.RequestError, httpx.HTTPStatusError):
        return templates.TemplateResponse("register.html", {"request": request, "msg": "Không thể kết nối đến dịch vụ khách hàng."})


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, msg: Optional[str] = None):
    return templates.TemplateResponse("login.html", {"request": request, "msg": msg})

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    login_payload = {"username": username, "password": password}
    
    # Try staff login first so admin account always lands on dashboard.
    try:
        async with httpx.AsyncClient(base_url=STAFF_SERVICE_URL) as client:
            response = await client.post("/api/auth/token/", json=login_payload)
        if response.status_code == 200:
            user_data = response.json()
            request.session["user"] = {"id": user_data.get("id"), "username": user_data.get("username"), "role": "staff"}
            return RedirectResponse(url="/admin", status_code=status.HTTP_302_FOUND)
    except httpx.RequestError:
        pass # Fall through to try customer login

    # Try customer login
    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            response = await client.post("/api/auth/token/", json=login_payload)
        if response.status_code == 200:
            user_data = response.json()
            request.session["user"] = {"id": user_data.get("id"), "username": user_data.get("username"), "role": "customer"}
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    except httpx.RequestError:
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Dịch vụ đăng nhập không khả dụng."})

    return templates.TemplateResponse("login.html", {"request": request, "msg": "Tên đăng nhập hoặc mật khẩu không đúng"})


@app.get("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/login")


@app.get("/books", response_class=HTMLResponse)
async def list_books(request: Request, user: dict = Depends(get_current_user)):
    search_query = {
        "title": request.query_params.get("title", ""),
        "category": request.query_params.get("category", "")
    }
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        page = 1
    page = max(page, 1)
    per_page = 12

    # Filter out empty search parameters before sending to the service
    api_params = {k: v for k, v in search_query.items() if v}

    books = []
    categories = []
    try:
        async with httpx.AsyncClient() as client:
            # Fetch books
            books_res = await client.get(f"{BOOK_SERVICE_URL}/api/books/", params=api_params)
            if books_res.status_code == 200:
                response_data = books_res.json()
                # Handle paginated response from book-service (e.g., {"results": [...]})
                if isinstance(response_data, dict) and 'results' in response_data:
                    books = response_data['results']
                else:
                    books = response_data # Fallback for non-paginated response
            # Fetch categories for the search form
            cat_res = await client.get(f"{BOOK_SERVICE_URL}/api/categories/")
            if cat_res.status_code == 200:
                categories = cat_res.json()

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error fetching books: {e}")

    total_books = len(books)
    total_pages = max(1, (total_books + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    books_paginated = books[start_idx:end_idx]

    preserved_query = {k: v for k, v in search_query.items() if v}
    query_base = urlencode(preserved_query)
    page_url_base = f"/books?{query_base}&" if query_base else "/books?"
        
    return templates.TemplateResponse("books.html", {
        "request": request, 
        "user": user, 
        "books": books_paginated,
        "total_books": total_books,
        "page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "page_url_base": page_url_base,
        "categories": categories,
        "search_query": search_query
    })


@app.get("/books/add", response_class=HTMLResponse)
async def add_book_get(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    categories = []
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            response = await client.get("/api/categories/")
            if response.status_code == 200:
                categories = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching categories: {e}")

    return templates.TemplateResponse("add_book.html", {"request": request, "user": user, "categories": categories})


@app.get("/books/{book_id}", response_class=HTMLResponse)
async def book_detail(request: Request, book_id: int, user: dict = Depends(get_current_user)):
    try:
        async with httpx.AsyncClient() as client:
            # Fetch book details
            book_response = await client.get(f"{BOOK_SERVICE_URL}/api/books/{book_id}/")
            if book_response.status_code == 404:
                raise HTTPException(status_code=404, detail="Sách không tồn tại")
            book_response.raise_for_status()
            book = book_response.json()

            # Fetch reviews for the book
            reviews_response = await client.get(f"{COMMENT_RATE_SERVICE_URL}/api/comment-rates", params={"book_id": book_id})
            if reviews_response.status_code == 200:
                reviews = reviews_response.json()
            else:
                reviews = []

            # Resolve customer names for review list
            customer_ids = sorted({r.get("customer_id") for r in reviews if r.get("customer_id") is not None})
            customer_name_map = {}
            if customer_ids:
                tasks = [
                    client.get(f"{CUSTOMER_SERVICE_URL}/api/customers/{customer_id}/")
                    for customer_id in customer_ids
                ]
                responses = await asyncio.gather(*tasks, return_exceptions=True)
                for customer_id, resp in zip(customer_ids, responses):
                    if isinstance(resp, Exception):
                        continue
                    if resp.status_code == 200:
                        customer_json = resp.json()
                        customer_name_map[customer_id] = customer_json.get("name") or customer_json.get("username")

            for review in reviews:
                customer_id = review.get("customer_id")
                review["customer_name"] = customer_name_map.get(customer_id)

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error fetching book detail or reviews: {e}")
        raise HTTPException(status_code=503, detail="Dịch vụ sách đang gặp sự cố.")
    return templates.TemplateResponse("book_detail.html", {
        "request": request, 
        "user": user, 
        "book": book,
        "reviews": reviews
    })


@app.get("/books/{book_id}/edit", response_class=HTMLResponse)
async def edit_book_get(request: Request, book_id: int, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    book, categories = None, []
    try:
        async with httpx.AsyncClient() as client:
            book_res = await client.get(f"{BOOK_SERVICE_URL}/api/books/{book_id}/")
            book_res.raise_for_status()
            book = book_res.json()

            cat_res = await client.get(f"{BOOK_SERVICE_URL}/api/categories/")
            if cat_res.status_code == 200:
                categories = cat_res.json()

    except (httpx.RequestError, httpx.HTTPStatusError):
        raise HTTPException(status_code=404, detail="Sách không tồn tại hoặc dịch vụ sách lỗi.")
    
    return templates.TemplateResponse("edit_book.html", {"request": request, "user": user, "book": book, "categories": categories})


@app.post("/books/{book_id}/edit")
async def edit_book_post(
    request: Request,
    book_id: int,
    title: str = Form(...),
    author: str = Form(...),
    category_id: Optional[str] = Form(None),
    price: float = Form(...),
    stock: int = Form(...),
    user: dict = Depends(get_current_user),
):
    role_required(user, ["staff"])
    parsed_category_id = None
    if category_id not in (None, ""):
        try:
            parsed_category_id = int(category_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Danh mục không hợp lệ.")

    book_data = {
        "title": title,
        "author": author,
        "category_id": parsed_category_id,
        "price": price, "stock": stock
    }
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            response = await client.put(f"/api/books/{book_id}/", json=book_data)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            raise HTTPException(status_code=400, detail=f"Dữ liệu cập nhật không hợp lệ: {e.response.text}")
        print(f"Error updating book: {e}")
        raise HTTPException(status_code=503, detail="Không thể cập nhật sách. Dịch vụ sách đang gặp sự cố.")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error updating book: {e}")
        raise HTTPException(status_code=503, detail="Không thể cập nhật sách. Dịch vụ sách đang gặp sự cố.")
    return RedirectResponse(url="/books", status_code=status.HTTP_302_FOUND)

@app.post("/books/{book_id}/delete")
async def delete_book(request: Request, book_id: int, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            response = await client.delete(f"/api/books/{book_id}/")
            response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error deleting book: {e}")
        # Optionally, redirect with an error message
    return RedirectResponse(url="/books", status_code=status.HTTP_302_FOUND)


@app.post("/books/{book_id}/review")
async def submit_review(
    request: Request,
    book_id: int,
    rating: int = Form(...),
    comment: str = Form(""),
    user: dict = Depends(get_current_user)
):
    role_required(user, ["customer"])
    customer_id = user.get("id")

    review_data = {
        "book_id": book_id,
        "customer_id": customer_id,
        "rating": rating,
        "comment": comment
    }

    try:
        async with httpx.AsyncClient(base_url=COMMENT_RATE_SERVICE_URL) as client:
            response = await client.post("/api/comment-rates", json=review_data)
            if response.status_code != 201:
                response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error submitting review: {e}")
    return RedirectResponse(url=f"/books/{book_id}", status_code=status.HTTP_302_FOUND)


@app.post("/books/{book_id}/add-to-cart")
async def add_to_cart(
    request: Request,
    book_id: int,
    quantity: int = Form(1),
    user: dict = Depends(get_current_user)
):
    role_required(user, ["customer"])
    customer_id = user.get("id")
    if not customer_id:
        raise HTTPException(status_code=403, detail="Không tìm thấy thông tin khách hàng.")
    if quantity < 1:
        quantity = 1

    try:
        # Check if book exists
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as book_client:
            book_res = await book_client.get(f"/api/books/{book_id}/")
            if book_res.status_code == 404:
                raise HTTPException(status_code=404, detail="Sách không tồn tại")
            book_res.raise_for_status()

        # Add to cart
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as cart_client:
            # Assuming cart_id is the same as customer_id and this endpoint adds/updates an item.
            cart_item_data = {"book_id": book_id, "quantity": quantity}
            response = await cart_client.post(f"/api/carts/{customer_id}/", json=cart_item_data)
            response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error adding to cart: {e}")
        raise HTTPException(status_code=503, detail="Dịch vụ giỏ hàng hoặc sách đang gặp sự cố.")

    return RedirectResponse(url="/cart", status_code=status.HTTP_302_FOUND)


@app.get("/cart", response_class=HTMLResponse)
async def view_cart(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["customer"])
    customer_id = user.get("id")
    items, total = [], 0
    if not customer_id:
        return templates.TemplateResponse("cart.html", {"request": request, "user": user, "items": [], "total": 0})

    try:
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as cart_client:
            cart_res = await cart_client.get(f"/api/carts/{customer_id}/")
            cart_items = cart_res.json().get("items", []) if cart_res.status_code == 200 else []

        if cart_items:
            book_ids = [item['book_id'] for item in cart_items]
            async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as book_client:
                tasks = [book_client.get(f"/api/books/{book_id}/") for book_id in book_ids]
                responses = await asyncio.gather(*tasks)
            
            book_details_map = {book.json()['id']: book.json() for book in responses if book.status_code == 200}

            for item in cart_items:
                book_detail = book_details_map.get(item['book_id'])
                if book_detail:
                    book_detail['quantity'] = item['quantity']
                    items.append(book_detail)
                    total += float(book_detail['price']) * item['quantity']
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error viewing cart: {e}")

    return templates.TemplateResponse("cart.html", {"request": request, "user": user, "items": items, "total": total})


@app.get("/checkout", response_class=HTMLResponse)
async def checkout_get(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["customer"])
    customer_id = user.get("id")
    
    try:
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as cart_client:
            cart_res = await cart_client.get(f"/api/carts/{customer_id}/")
            cart_items = cart_res.json().get("items", []) if cart_res.status_code == 200 else []
    except httpx.RequestError:
        cart_items = []

    if not cart_items:
        return RedirectResponse(url="/cart", status_code=status.HTTP_302_FOUND)

    # Fetch book details for summary
    items_for_display, total = [], 0
    book_ids = [item['book_id'] for item in cart_items]
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as book_client:
            tasks = [book_client.get(f"/api/books/{book_id}/") for book_id in book_ids]
            responses = await asyncio.gather(*tasks)
        book_details_map = {book.json()['id']: book.json() for book in responses if book.status_code == 200}
        for item in cart_items:
            book_detail = book_details_map.get(item['book_id'])
            if book_detail:
                items_for_display.append(book_detail)
                total += float(book_detail['price']) * item['quantity']
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error fetching book details for checkout: {e}")
    
    addresses = user.get("addresses", [])
    default_address = next((addr for addr in addresses if addr.get("is_default")), None)
    default_address_id = (
        default_address.get("id")
        if default_address
        else (addresses[0].get("id") if addresses else None)
    )

    return templates.TemplateResponse("checkout.html", {
        "request": request, 
        "user": user, 
        "items": items_for_display, 
        "total": total,
        "addresses": addresses,
        "default_address_id": default_address_id,
    })


@app.post("/checkout")
async def checkout_post(
    request: Request,
    payment_method: str = Form(...),
    selected_address: Optional[str] = Form(None),
    # Fields for a new address, optional
    new_recipient_name: Optional[str] = Form(None),
    new_phone_number: Optional[str] = Form(None),
    new_address_line: Optional[str] = Form(None),
    new_city: Optional[str] = Form(None),
    new_province: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    role_required(user, ["customer"])
    customer_id = user.get("id")

    # Verify cart is not empty
    try:
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as client:
            cart_res = await client.get(f"/api/carts/{customer_id}/")
            cart_items = cart_res.json().get("items", []) if cart_res.status_code == 200 else []
        if not cart_items:
            return RedirectResponse(url="/cart", status_code=status.HTTP_302_FOUND)
    except httpx.RequestError:
        return RedirectResponse(url="/cart", status_code=status.HTTP_302_FOUND)

    # Fetch cart items and details again to build the order
    try:
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as cart_client:
            cart_res = await cart_client.get(f"/api/carts/{customer_id}/")
            cart_items_data = cart_res.json().get("items", []) if cart_res.status_code == 200 else []

        book_ids = [item['book_id'] for item in cart_items_data]
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as book_client:
            tasks = [book_client.get(f"/api/books/{book_id}/") for book_id in book_ids]
            responses = await asyncio.gather(*tasks)
        book_details_map = {book.json()['id']: book.json() for book in responses if book.status_code == 200}

        order_items_payload = []
        stock_updates = []
        total_price = 0
        for item in cart_items_data:
            book = book_details_map.get(item['book_id'])
            if book:
                requested_qty = int(item['quantity'])
                current_stock = int(book.get('stock', 0))
                if requested_qty > current_stock:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Sách '{book['title']}' chỉ còn {current_stock} sản phẩm trong kho."
                    )

                book_price = float(book['price'])
                order_items_payload.append({
                    "book_id": book['id'],
                    "quantity": requested_qty,
                    "price_at_purchase": book_price,
                    "book_title": book['title']
                })
                total_price += book_price * requested_qty
                stock_updates.append({
                    "book_id": book['id'],
                    "new_stock": current_stock - requested_qty,
                })

        if not order_items_payload:
            raise HTTPException(status_code=400, detail="Không tìm thấy sản phẩm hợp lệ trong giỏ hàng.")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        raise HTTPException(status_code=503, detail=f"Lỗi khi chuẩn bị đơn hàng: {e}")

    # Determine shipping address
    shipping_address_obj = {}
    user_addresses = user.get("addresses", []) or []

    if selected_address == "new":
        if not all([new_recipient_name, new_phone_number, new_address_line, new_city, new_province]):
            raise HTTPException(status_code=400, detail="Vui lòng điền đầy đủ thông tin địa chỉ mới.")
        new_address_data = {
            "recipient_name": new_recipient_name,
            "phone_number": new_phone_number,
            "address_line": new_address_line,
            "city": new_city,
            "province": new_province,
        }
        try:
            async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
                response = await client.post(f"/api/customers/{customer_id}/addresses/", json=new_address_data)
                response.raise_for_status()
                created_address = response.json()
                shipping_address_obj = {
                    "recipient_name": created_address["recipient_name"],
                    "phone_number": created_address["phone_number"],
                    "address": f"{created_address['address_line']}, {created_address['city']}, {created_address['province']}"
                }
        except (httpx.RequestError, httpx.HTTPStatusError):
            raise HTTPException(status_code=503, detail="Không thể lưu địa chỉ mới.")
    else:
        addr = None
        if selected_address:
            try:
                addr_id = int(selected_address)
            except ValueError:
                raise HTTPException(status_code=400, detail="Địa chỉ đã chọn không hợp lệ.")

            addr = next((a for a in user_addresses if a.get("id") == addr_id), None)
            if not addr:
                raise HTTPException(status_code=400, detail="Địa chỉ đã chọn không hợp lệ.")
        else:
            addr = next((a for a in user_addresses if a.get("is_default")), None)
            if not addr and user_addresses:
                addr = user_addresses[0]

        if not addr:
            raise HTTPException(status_code=400, detail="Bạn chưa có địa chỉ mặc định. Vui lòng thêm địa chỉ mới.")

        shipping_address_obj = {
            "recipient_name": addr["recipient_name"],
            "phone_number": addr["phone_number"],
            "address": f"{addr['address_line']}, {addr['city']}, {addr['province']}"
        }

    # Create Order via Order Service
    order_payload = {
        "customer_id": customer_id,
        "items": order_items_payload,
        "total_price": total_price,
        "payment_method": payment_method,
        "shipping_address": f"{shipping_address_obj['recipient_name']}, {shipping_address_obj['phone_number']}, {shipping_address_obj['address']}",
        "status": "processing" if payment_method == "cod" else "pending_payment"
    }

    try:
        async with httpx.AsyncClient(base_url=ORDER_SERVICE_URL) as client:
            response = await client.post("/api/orders", json=order_payload)
            response.raise_for_status()
            created_order = response.json()
            order_code = created_order['order_code']
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error creating order: {e}")
        raise HTTPException(status_code=503, detail="Không thể tạo đơn hàng, dịch vụ đang gặp sự cố.")

    # Deduct inventory after successful order creation
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            update_tasks = [
                client.put(f"/api/books/{item['book_id']}/", json={"stock": item["new_stock"]})
                for item in stock_updates
            ]
            update_responses = await asyncio.gather(*update_tasks)

        failed_updates = [res for res in update_responses if res.status_code >= 400]
        if failed_updates:
            raise HTTPException(
                status_code=503,
                detail=f"Đơn hàng {order_code} đã tạo nhưng không thể cập nhật tồn kho. Vui lòng liên hệ quản trị viên."
            )
    except httpx.RequestError as e:
        print(f"Error updating stock after order: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Đơn hàng {order_code} đã tạo nhưng không thể cập nhật tồn kho. Vui lòng liên hệ quản trị viên."
        )

    # Clear the cart in cart-service
    try:
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as client:
            await client.delete(f"/api/carts/{customer_id}/")
    except httpx.RequestError as e:
        print(f"Could not clear cart for customer {customer_id}: {e}")

    # Redirect to payment/complete
    if payment_method == "bank_transfer":
        return RedirectResponse(url=f"/order/{order_code}/payment-info", status_code=status.HTTP_302_FOUND)
    else: # COD
        return RedirectResponse(url=f"/order/{order_code}/complete", status_code=status.HTTP_302_FOUND)


@app.get("/order/{order_code}/complete", response_class=HTMLResponse)
async def order_complete(request: Request, order_code: str, user: dict = Depends(get_current_user)):
    role_required(user, ["customer", "staff"])
    order = await get_order_by_code(order_code)
    return templates.TemplateResponse("order_complete.html", {"request": request, "user": user, "order": order})


@app.get("/order/{order_code}/payment-info", response_class=HTMLResponse)
async def payment_info(request: Request, order_code: str, user: dict = Depends(get_current_user)):
    role_required(user, ["customer"])
    order = await get_order_by_code(order_code)
    if order.get("payment_method") != "bank_transfer":
        raise HTTPException(status_code=404, detail="Đơn hàng không hợp lệ hoặc không yêu cầu thanh toán chuyển khoản.")
    bank_info = {
        "bank_name": "Ngân hàng Demo Techcombank",
        "account_number": "19031234567890",
        "account_holder": "CONG TY TNHH BOOKSTORE",
        "transfer_content": f"Thanh toan don hang {order_code}"
    }
    return templates.TemplateResponse("payment_info.html", {"request": request, "user": user, "order": order, "bank_info": bank_info})


@app.post("/order/{order_code}/confirm-payment")
async def confirm_payment(request: Request, order_code: str, user: dict = Depends(get_current_user)):
    # This is a mock endpoint. In a real app, this would be a webhook called by the bank/payment gateway,
    # or an action performed by an admin in the back office.
    # For this demo, we allow the customer to "confirm" their own payment.
    
    order = await get_order_by_code(order_code)

    try:
        async with httpx.AsyncClient(base_url=ORDER_SERVICE_URL) as client:
            response = await client.patch(f"/api/orders/{order['id']}/status", params={"status": "processing"})
            if response.status_code == 404:
                raise HTTPException(status_code=404, detail="Đơn hàng không tìm thấy")
            response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error confirming payment: {e}")
        raise HTTPException(status_code=503, detail="Không thể xác nhận thanh toán.")
    
    return RedirectResponse(url=f"/order/{order_code}/complete", status_code=status.HTTP_302_FOUND)


@app.get("/account", response_class=HTMLResponse)
async def view_account(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["customer", "staff"]) # Allow staff to see their account too
    user_orders = []
    if user['role'] == 'customer':
        try:
            async with httpx.AsyncClient(base_url=ORDER_SERVICE_URL) as client:
                response = await client.get(f"/api/orders?customer_id={user['id']}")
                if response.status_code == 200:
                    user_orders = response.json()
        except httpx.RequestError as e:
            print(f"Error fetching user orders: {e}")
    return templates.TemplateResponse("account.html", {"request": request, "user": user, "user_orders": user_orders})

@app.get("/account/addresses", response_class=HTMLResponse)
async def manage_addresses(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["customer"])
    return templates.TemplateResponse("account_addresses.html", {"request": request, "user": user, "addresses": user.get("addresses", [])})

@app.post("/account/addresses/add")
async def add_address(
    request: Request,
    recipient_name: str = Form(...),
    phone_number: str = Form(...),
    address_line: str = Form(...),
    city: str = Form(...),
    province: str = Form(...),
    is_default: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    role_required(user, ["customer"])
    customer_id = user.get("id")
    new_address_data = {
        "recipient_name": recipient_name,
        "phone_number": phone_number,
        "address_line": address_line,
        "city": city,
        "province": province,
        "is_default": is_default == "on"
    }
    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            response = await client.post(f"/api/customers/{customer_id}/addresses/", json=new_address_data)
            response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error adding address: {e}")
        # Optionally, redirect with an error message
    return RedirectResponse(url="/account/addresses", status_code=status.HTTP_302_FOUND)


@app.post("/account/addresses/{addr_id}/delete")
async def delete_address(request: Request, addr_id: int, user: dict = Depends(get_current_user)):
    role_required(user, ["customer"])
    customer_id = user.get("id")
    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            response = await client.delete(f"/api/customers/{customer_id}/addresses/{addr_id}/")
            response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error deleting address: {e}")
    return RedirectResponse(url="/account/addresses", status_code=status.HTTP_302_FOUND)


@app.post("/account/addresses/{addr_id}/default")
async def set_default_address(request: Request, addr_id: int, user: dict = Depends(get_current_user)):
    role_required(user, ["customer"])
    customer_id = user.get("id")
    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            # customer-service handles unsetting other defaults via the model's save() method
            response = await client.put(f"/api/customers/{customer_id}/addresses/{addr_id}/", json={"is_default": True})
            response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error setting default address: {e}")
        # Optionally, redirect with an error message
    return RedirectResponse(url="/account/addresses", status_code=status.HTTP_302_FOUND)


@app.post("/books/add")
async def add_book_post(
    request: Request,
    title: str = Form(...),
    author: str = Form(...),
    category_id: Optional[str] = Form(None),
    price: float = Form(...),
    stock: int = Form(...),
    user: dict = Depends(get_current_user),
):
    role_required(user, ["staff"])
    parsed_category_id = None
    if category_id not in (None, ""):
        try:
            parsed_category_id = int(category_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Danh mục không hợp lệ.")

    new_book = {"title": title, "author": author, "category_id": parsed_category_id, "price": price, "stock": stock}
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            response = await client.post("/api/books/", json=new_book)
            response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error adding book: {e}")
        raise HTTPException(status_code=503, detail="Không thể thêm sách. Dịch vụ sách đang gặp sự cố.")
    return RedirectResponse(url="/books", status_code=status.HTTP_302_FOUND)


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    books, orders, carts, customers = [], [], [], []
    review_count = 0
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            response = await client.get("/api/books/?limit=100") # Fetch more books for admin view
            if response.status_code == 200:
                response_data = response.json()
                # Handle paginated response from book-service (e.g., {"results": [...]})
                if isinstance(response_data, dict) and 'results' in response_data:
                    books = response_data['results']
                else:
                    books = response_data

            if books:
                review_res = await client.get(f"{COMMENT_RATE_SERVICE_URL}/api/comment-rates")
                if review_res.status_code == 200:
                    review_count = len(review_res.json())
    except httpx.RequestError:
        pass  # Ignore book service error, show empty list

    try:
        async with httpx.AsyncClient(base_url=ORDER_SERVICE_URL) as client:
            response = await client.get("/api/orders")
            if response.status_code == 200:
                orders = response.json()
    except httpx.RequestError:
        pass

    try:
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as client:
            response = await client.get("/api/carts/")
            if response.status_code == 200:
                carts = response.json()
    except httpx.RequestError:
        pass

    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            response = await client.get("/api/customers/")
            if response.status_code == 200:
                customers = response.json()
    except httpx.RequestError:
        pass

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "books": books,
        "stats": {
            "book_count": len(books),
            "order_count": len(orders),
            "cart_count": len(carts),
            "customer_count": len(customers),
            "review_count": review_count,
        }
    })


@app.get("/admin/customers", response_class=HTMLResponse)
async def admin_customers_list(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    customers, orders = [], []

    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            response = await client.get("/api/customers/")
            if response.status_code == 200:
                customers = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching customers: {e}")

    try:
        async with httpx.AsyncClient(base_url=ORDER_SERVICE_URL) as client:
            response = await client.get("/api/orders")
            if response.status_code == 200:
                orders = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching orders for customer stats: {e}")

    order_count_map = {}
    for order in orders:
        customer_id = order.get("customer_id")
        if customer_id is not None:
            order_count_map[customer_id] = order_count_map.get(customer_id, 0) + 1

    return templates.TemplateResponse("admin_customers.html", {
        "request": request,
        "user": user,
        "customers": customers,
        "order_count_map": order_count_map,
    })


@app.get("/admin/carts", response_class=HTMLResponse)
async def admin_carts_list(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    carts, customers = [], []

    try:
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as client:
            response = await client.get("/api/carts/")
            if response.status_code == 200:
                carts = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching carts: {e}")

    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            response = await client.get("/api/customers/")
            if response.status_code == 200:
                customers = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching customers for cart mapping: {e}")

    customer_map = {customer.get("id"): customer for customer in customers}
    for cart in carts:
        cart["item_count"] = sum(item.get("quantity", 0) for item in cart.get("items", []))

    return templates.TemplateResponse("admin_carts.html", {
        "request": request,
        "user": user,
        "carts": carts,
        "customer_map": customer_map,
    })


@app.post("/admin/carts/{customer_id}/clear")
async def admin_clear_cart(request: Request, customer_id: int, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    try:
        async with httpx.AsyncClient(base_url=CART_SERVICE_URL) as client:
            await client.delete(f"/api/carts/{customer_id}/")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error clearing cart for customer {customer_id}: {e}")
    return RedirectResponse(url="/admin/carts", status_code=status.HTTP_302_FOUND)


@app.get("/admin/reviews", response_class=HTMLResponse)
async def admin_reviews_list(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    books, customers = [], []
    reviews = []

    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            response = await client.get("/api/books/")
            if response.status_code == 200:
                books = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching books for reviews: {e}")

    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL) as client:
            response = await client.get("/api/customers/")
            if response.status_code == 200:
                customers = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching customers for reviews: {e}")

    customer_map = {customer.get("id"): customer for customer in customers}

    if books:
        try:
            book_map = {book.get("id"): book for book in books}
            async with httpx.AsyncClient(base_url=COMMENT_RATE_SERVICE_URL) as client:
                review_response = await client.get("/api/comment-rates")

            if review_response.status_code == 200:
                for review in review_response.json():
                    book = book_map.get(review.get("book_id"), {})
                    customer = customer_map.get(review.get("customer_id"), {})
                    reviews.append({
                        "id": review.get("id"),
                        "book_id": review.get("book_id"),
                        "book_title": book.get("title") or f"Sách #{review.get('book_id')}",
                        "customer_id": review.get("customer_id"),
                        "customer_name": customer.get("name") or customer.get("username") or f"ID {review.get('customer_id')}",
                        "rating": review.get("rating"),
                        "comment": review.get("comment", ""),
                        "created_at": review.get("created_at"),
                    })
        except httpx.RequestError as e:
            print(f"Error fetching review details: {e}")

    reviews.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return templates.TemplateResponse("admin_reviews.html", {
        "request": request,
        "user": user,
        "reviews": reviews,
    })


@app.post("/admin/reviews/{book_id}/{review_id}/delete")
async def admin_delete_review(request: Request, book_id: int, review_id: str, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    try:
        async with httpx.AsyncClient(base_url=COMMENT_RATE_SERVICE_URL) as client:
            await client.delete(f"/api/comment-rates/{review_id}")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error deleting review {review_id}: {e}")
    return RedirectResponse(url="/admin/reviews", status_code=status.HTTP_302_FOUND)

@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders_list(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    orders = []
    try:
        async with httpx.AsyncClient(base_url=ORDER_SERVICE_URL) as client:
            response = await client.get("/api/orders")
            if response.status_code == 200:
                orders = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching all orders: {e}")
    
    return templates.TemplateResponse("admin_orders.html", {
        "request": request, 
        "user": user, 
        "orders": orders
    })


@app.post("/admin/orders/{order_code}/update-status")
async def admin_update_order_status(
    request: Request,
    order_code: str,
    status: str = Form(...),
    user: dict = Depends(get_current_user)
):
    role_required(user, ["staff"])
    order = await get_order_by_code(order_code)
    try:
        async with httpx.AsyncClient(base_url=ORDER_SERVICE_URL) as client:
            await client.patch(f"/api/orders/{order['id']}/status", params={"status": status})
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error updating order status: {e}")
    return RedirectResponse(url="/admin/orders", status_code=status.HTTP_302_FOUND)


@app.get("/admin/categories", response_class=HTMLResponse)
async def admin_categories_list(request: Request, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    categories = []
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            response = await client.get("/api/categories/")
            if response.status_code == 200:
                categories = response.json()
    except httpx.RequestError as e:
        print(f"Error fetching categories: {e}")
    return templates.TemplateResponse("admin_categories.html", {"request": request, "user": user, "categories": categories})


@app.post("/admin/categories/add")
async def admin_add_category(request: Request, name: str = Form(...), description: Optional[str] = Form(None), user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            await client.post("/api/categories/", json={"name": name, "description": description})
    except httpx.RequestError as e:
        print(f"Error adding category: {e}")
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)


@app.get("/admin/categories/{cat_id}/edit", response_class=HTMLResponse)
async def admin_edit_category_get(request: Request, cat_id: int, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    try:
        async with httpx.AsyncClient(base_url=BOOK_SERVICE_URL) as client:
            response = await client.get(f"/api/categories/{cat_id}/")
            response.raise_for_status()
            category = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError):
        raise HTTPException(status_code=404, detail="Category not found")
    return templates.TemplateResponse("admin_category_edit.html", {"request": request, "user": user, "category": category})


@app.post("/admin/categories/{cat_id}/edit")
async def admin_edit_category_post(request: Request, cat_id: int, name: str = Form(...), description: Optional[str] = Form(None), user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    async with httpx.AsyncClient() as client:
        await client.put(f"{BOOK_SERVICE_URL}/api/categories/{cat_id}/", json={"name": name, "description": description})
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)


@app.post("/admin/categories/{cat_id}/delete")
async def admin_delete_category(request: Request, cat_id: int, user: dict = Depends(get_current_user)):
    role_required(user, ["staff"])
    async with httpx.AsyncClient() as client:
        await client.delete(f"{BOOK_SERVICE_URL}/api/categories/{cat_id}/")
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)
