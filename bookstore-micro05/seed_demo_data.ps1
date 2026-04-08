$ErrorActionPreference = 'Stop'

$bookApi = 'http://localhost:8003/api'

$targetCategories = @(
    @{ name = 'VÄƒn há»c'; description = 'Tiá»ƒu thuyáº¿t vĂ  tĂ¡c pháº©m vÄƒn há»c' },
    @{ name = 'Kinh doanh'; description = 'Quáº£n trá»‹, marketing, khá»Ÿi nghiá»‡p' },
    @{ name = 'CĂ´ng nghá»‡'; description = 'Láº­p trĂ¬nh, dá»¯ liá»‡u, AI' },
    @{ name = 'Khoa há»c'; description = 'Phá»• biáº¿n kiáº¿n thá»©c khoa há»c' },
    @{ name = 'TĂ¢m lĂ½ - Ká»¹ nÄƒng'; description = 'PhĂ¡t triá»ƒn báº£n thĂ¢n vĂ  giao tiáº¿p' },
    @{ name = 'Lá»‹ch sá»­'; description = 'Lá»‹ch sá»­ Viá»‡t Nam vĂ  tháº¿ giá»›i' },
    @{ name = 'Thiáº¿u nhi'; description = 'SĂ¡ch cho tráº» em vĂ  thiáº¿u niĂªn' }
)

$booksByCategory = @{
    'VÄƒn há»c' = @(
        @{ title='MÆ°a Háº¡ Cuá»‘i Phá»‘'; author='LĂª Minh HĂ '; price=98000 },
        @{ title='Con ÄÆ°á»ng Vá» NhĂ '; author='Nguyá»…n HoĂ ng Nam'; price=105000 },
        @{ title='ÄĂªm TrÄƒng BĂªn SĂ´ng'; author='Tráº§n Thá»‹ Lan'; price=92000 },
        @{ title='Giá»t Náº¯ng Sau MÆ°a'; author='Pháº¡m Quá»³nh Anh'; price=110000 },
        @{ title='NgÆ°á»i Ká»ƒ Chuyá»‡n GiĂ³'; author='ÄoĂ n Nháº­t Minh'; price=97000 },
        @{ title='Phá»‘ Cá»• MĂ¹a ÄĂ´ng'; author='BĂ¹i Thanh TĂ¹ng'; price=89000 },
        @{ title='Miá»n KĂ½ á»¨c'; author='VĂµ Mai HÆ°Æ¡ng'; price=101000 },
        @{ title='Khoáº£ng Trá»i Sau Ă” Cá»­a'; author='Äáº·ng KhĂ¡nh Linh'; price=96000 }
    )
    'Kinh doanh' = @(
        @{ title='Quáº£n Trá»‹ BĂ¡n HĂ ng Hiá»‡u Quáº£'; author='HoĂ ng Quá»‘c Viá»‡t'; price=165000 },
        @{ title='Nghi Thá»©c Há»p Chiáº¿n LÆ°á»£c'; author='Nguyá»…n Äá»©c Phong'; price=172000 },
        @{ title='Khá»Ÿi Nghiá»‡p Tinh Gá»n'; author='LĂª Quang Huy'; price=158000 },
        @{ title='Váº­n HĂ nh Doanh Nghiá»‡p Nhá»'; author='Tráº§n Ngá»c BĂ­ch'; price=149000 },
        @{ title='TÆ° Duy TĂ i ChĂ­nh Cho Chá»§ Shop'; author='Pháº¡m Minh ChĂ¢u'; price=139000 },
        @{ title='Marketing Ná»™i Dung Tá»« A Äáº¿n Z'; author='Äá»— Háº£i Nam'; price=176000 },
        @{ title='LĂ£nh Äáº¡o Äá»™i NhĂ³m Linh Hoáº¡t'; author='VÅ© Anh Tuáº¥n'; price=168000 },
        @{ title='Chiáº¿n LÆ°á»£c GiĂ¡ BĂ¡n'; author='Nguyá»…n Thá»‹ Thu'; price=154000 }
    )
    'CĂ´ng nghá»‡' = @(
        @{ title='Python Data Practical'; author='Nguyá»…n Tiáº¿n Äáº¡t'; price=245000 },
        @{ title='Kiáº¿n TrĂºc Microservice CÆ¡ Báº£n'; author='LĂª Quá»‘c KhĂ¡nh'; price=228000 },
        @{ title='Nháº­p MĂ´n Machine Learning'; author='Pháº¡m Äá»©c Long'; price=239000 },
        @{ title='Thiáº¿t Káº¿ API Chuáº©n HĂ³a'; author='BĂ¹i Anh Khoa'; price=219000 },
        @{ title='Docker Cho NgÆ°á»i Má»›i'; author='Tráº§n Gia Báº£o'; price=187000 },
        @{ title='Clean Code Thá»±c Chiáº¿n'; author='Äá»— Minh Äá»©c'; price=255000 },
        @{ title='Há»‡ Quáº£n Trá»‹ CÆ¡ Sá»Ÿ Dá»¯ Liá»‡u'; author='NgĂ´ Thanh SÆ¡n'; price=233000 },
        @{ title='TÆ° Duy Kiá»ƒm Thá»­ Pháº§n Má»m'; author='HoĂ ng Lan Chi'; price=198000 }
    )
    'Khoa há»c' = @(
        @{ title='KhĂ¡m PhĂ¡ VÅ© Trá»¥ Gáº§n'; author='LĂª Anh QuĂ¢n'; price=144000 },
        @{ title='NĂ£o Bá»™ vĂ  TrĂ­ Nhá»›'; author='Pháº¡m Thá»‹ NgĂ¢n'; price=152000 },
        @{ title='Sinh Há»c Trong Äá»i Sá»‘ng'; author='Nguyá»…n VÄƒn Kiá»‡t'; price=138000 },
        @{ title='Váº­t LĂ½ Quanh Ta'; author='Äá»— Minh Tuáº¥n'; price=141000 },
        @{ title='Khoa Há»c Vá» Giáº¥c Ngá»§'; author='Tráº§n HĂ  Linh'; price=147000 },
        @{ title='ToĂ¡n TÆ° Duy Logic'; author='BĂ¹i Quá»‘c DÅ©ng'; price=136000 },
        @{ title='Khoa Há»c KhĂ­ Háº­u'; author='Nguyá»…n Há»¯u TĂ¢m'; price=159000 },
        @{ title='Giáº£i MĂ£ Gen NgÆ°á»i'; author='LĂª Mai Anh'; price=166000 }
    )
    'TĂ¢m lĂ½ - Ká»¹ nÄƒng' = @(
        @{ title='ThĂ³i Quen Nhá» Káº¿t Quáº£ Lá»›n'; author='Tráº§n Quá»‘c HÆ°ng'; price=128000 },
        @{ title='Giao Tiáº¿p KhĂ´ng Xung Äá»™t'; author='Pháº¡m Ngá»c HĂ '; price=121000 },
        @{ title='Quáº£n LĂ½ Cáº£m XĂºc'; author='Nguyá»…n Thá»‹ Há»“ng'; price=117000 },
        @{ title='Tá»± Tin NĂ³i TrÆ°á»›c ÄĂ¡m ÄĂ´ng'; author='Äá»— Thá»‹ Mai'; price=109000 },
        @{ title='LĂ m Viá»‡c SĂ¢u Táº­p Trung'; author='LĂª Tuáº¥n Khang'; price=132000 },
        @{ title='Äá»c Hiá»ƒu TĂ¢m LĂ½ KhĂ¡ch HĂ ng'; author='VĂµ Thanh Nam'; price=126000 },
        @{ title='Ká»¹ NÄƒng ÄĂ m PhĂ¡n'; author='Nguyá»…n Báº£o TrĂ¢m'; price=134000 },
        @{ title='Sá»‘ng CĂ³ Má»¥c TiĂªu'; author='BĂ¹i Minh PhĂºc'; price=118000 }
    )
    'Lá»‹ch sá»­' = @(
        @{ title='Lá»‹ch Sá»­ Viá»‡t Nam RĂºt Gá»n'; author='NgĂ´ Minh TrĂ­'; price=157000 },
        @{ title='VÄƒn Minh SĂ´ng Há»“ng'; author='Tráº§n Äá»©c Hiáº¿u'; price=149000 },
        @{ title='Tháº¿ Giá»›i Cáº­n Äáº¡i'; author='Pháº¡m Quang An'; price=171000 },
        @{ title='Con ÄÆ°á»ng TÆ¡ Lá»¥a'; author='LĂª Thá»‹ Thu'; price=146000 },
        @{ title='Lá»‹ch Sá»­ ÄĂ´ Thá»‹ SĂ i GĂ²n'; author='Nguyá»…n Gia Báº£o'; price=163000 },
        @{ title='Chiáº¿n Tranh vĂ  HĂ²a BĂ¬nh ChĂ¢u Ă'; author='VĂµ Äá»©c Tháº¯ng'; price=174000 },
        @{ title='Danh NhĂ¢n Viá»‡t Nam'; author='BĂ¹i Thanh SÆ¡n'; price=138000 },
        @{ title='Lá»‹ch Sá»­ Biá»ƒn ÄĂ´ng'; author='Tráº§n Minh ChĂ¢u'; price=169000 }
    )
    'Thiáº¿u nhi' = @(
        @{ title='Chuyá»‡n Ká»ƒ TrÆ°á»›c Giá» Ngá»§'; author='Cá»• TĂ­ch Viá»‡t'; price=68000 },
        @{ title='NhĂ  ThĂ¡m Hiá»ƒm Nhá»'; author='Nguyá»…n Nhi'; price=72000 },
        @{ title='Khoa Há»c Nhá» Vui'; author='LĂª CĂ¡t'; price=79000 },
        @{ title='Tá»« Äiá»ƒn HĂ¬nh áº¢nh Äáº§u Äá»i'; author='Pháº¡m UyĂªn'; price=83000 },
        @{ title='Báº£n ThĂ¢n Tá»a SĂ¡ng'; author='Äá»— CĂ¡t TiĂªn'; price=76000 },
        @{ title='HĂ nh Tinh Ká»³ Diá»‡u'; author='Tráº§n Báº£o An'; price=81000 },
        @{ title='MĂ u Sáº¯c Cá»§a Rá»«ng'; author='VĂµ NgĂ¢n HĂ '; price=74000 },
        @{ title='Láº­p TrĂ¬nh Báº±ng Khá»‘i'; author='Nguyá»…n Gia Linh'; price=95000 }
    )
}

# Build/ensure category map
$existingCategories = Invoke-RestMethod -Uri "$bookApi/categories/" -Method Get
$categoryMap = @{}
foreach ($c in $existingCategories) {
    $categoryMap[$c.name] = $c.id
}
foreach ($cat in $targetCategories) {
    if (-not $categoryMap.ContainsKey($cat.name)) {
        $created = Invoke-RestMethod -Uri "$bookApi/categories/" -Method Post -ContentType 'application/json' -Body ($cat | ConvertTo-Json)
        $categoryMap[$created.name] = $created.id
    }
}

# Remove all current books
$existingBooks = Invoke-RestMethod -Uri "$bookApi/books/" -Method Get
foreach ($book in $existingBooks) {
    Invoke-RestMethod -Uri "$bookApi/books/$($book.id)/" -Method Delete | Out-Null
}

# Seed exactly 50 books in round-robin across 7 categories (no suffix 'Báº£n ...')
$categoryNames = @($targetCategories | ForEach-Object { $_.name })
$createdCount = 0
for ($i = 0; $i -lt 50; $i++) {
    $catName = $categoryNames[$i % $categoryNames.Count]
    $pool = $booksByCategory[$catName]
    $template = $pool[[math]::Floor($i / $categoryNames.Count) % $pool.Count]

    $payload = @{
        title = $template.title
        author = $template.author
        category_id = [int]$categoryMap[$catName]
        price = [double]$template.price
        image_url = "https://picsum.photos/seed/vnbook$($i+1)/360/520"
        description = "SĂ¡ch $catName cháº¥t lÆ°á»£ng cao dĂ nh cho ngÆ°á»i Ä‘á»c hiá»‡n Ä‘áº¡i."
        stock = 25 + (($i + 1) % 35)
    }

    Invoke-RestMethod -Uri "$bookApi/books/" -Method Post -ContentType 'application/json' -Body ($payload | ConvertTo-Json) | Out-Null
    $createdCount++
}

$books = Invoke-RestMethod -Uri "$bookApi/books/" -Method Get
$distribution = $books | Group-Object category | Sort-Object Name | ForEach-Object {
    [PSCustomObject]@{ category = $_.Name; count = $_.Count }
}

$result = [PSCustomObject]@{
    books_created = $createdCount
    books_total = $books.Count
    distribution = $distribution
    sample_titles = @($books | Select-Object -First 8 | ForEach-Object { $_.title })
}

$result | ConvertTo-Json -Depth 6

