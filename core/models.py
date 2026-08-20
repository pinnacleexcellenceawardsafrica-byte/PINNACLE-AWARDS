from django.db import models
from django.utils import timezone
from django.utils.text import slugify

class SiteSettings(models.Model):
    site_name = models.CharField(max_length=200, default='Pinnacle Excellence Awards Africa')
    tagline = models.CharField(max_length=500, default='Celebrating Excellence. Inspiring Impact. Honouring Greatness.')
    voting_open = models.BooleanField(default=True)
    results_live = models.BooleanField(default=False)
    countdown_label = models.CharField(max_length=100, default='The Night Begins In')
    countdown_date = models.DateTimeField(default=timezone.now)
    footer_text = models.TextField(blank=True)
    
    # Paystack Settings
    paystack_secret_key = models.CharField(max_length=255, blank=True, default='')
    paystack_public_key = models.CharField(max_length=255, blank=True, default='')
    paystack_active = models.BooleanField(default=False)
    
    def __str__(self):
        return self.site_name
    
    class Meta:
        verbose_name_plural = "Site Settings"

class Category(models.Model):
    GROUP_CHOICES = [
        ('Entertainment', 'Entertainment'),
        ('Creative', 'Creative'),
        ('Business', 'Business'),
        ('Leadership', 'Leadership'),
        ('Innovation', 'Innovation'),
        ('Social Impact', 'Social Impact'),
    ]
    
    name = models.CharField(max_length=200)
    group = models.CharField(max_length=50, choices=GROUP_CHOICES)
    description = models.TextField(blank=True)
    slug = models.SlugField(unique=True, blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.name} ({self.group})"
    
    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['order', 'name']

class Nominee(models.Model):
    GENDER_CHOICES = [
        ('man', 'Man'),
        ('woman', 'Woman'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('active', 'Active'),
        ('rejected', 'Rejected'),
        ('draft', 'Draft'),
        ('completed', 'Completed'),
    ]
    
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='nominees')
    group = models.CharField(max_length=50, choices=Category.GROUP_CHOICES)
    description = models.TextField()
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='other')
    photo = models.ImageField(upload_to='nominees/', blank=True, null=True)
    votes = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    featured = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} - {self.category.name} ({self.get_status_display()})"
    
    class Meta:
        ordering = ['-votes', 'order', 'name']

class UserNomination(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    nominee_name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='user_nominations')
    description = models.TextField()
    nominator_name = models.CharField(max_length=200)
    nominator_email = models.EmailField()
    nominator_phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # When approved, link to the created nominee
    approved_nominee = models.ForeignKey(
        Nominee, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='user_nomination'
    )
    
    def __str__(self):
        return f"{self.nominee_name} - {self.nominator_name} ({self.get_status_display()})"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "User Nominations"

class Vote(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('M-Pesa', 'M-Pesa'),
        ('Paystack', 'Paystack'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Cash', 'Cash'),
    ]
    
    nominee = models.ForeignKey(Nominee, on_delete=models.CASCADE, related_name='votes_received')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='votes')
    voter_name = models.CharField(max_length=200, blank=True)
    voter_email = models.EmailField(blank=True)
    voter_phone = models.CharField(max_length=20, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True, unique=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=10.00)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, default='Paystack')
    payment_response = models.JSONField(blank=True, null=True)
    paystack_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Vote for {self.nominee.name} - KSH {self.amount}"
    
    class Meta:
        ordering = ['-created_at']

class GalleryImage(models.Model):
    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to='gallery/')
    description = models.TextField(blank=True)
    featured = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.title
    
    class Meta:
        verbose_name_plural = "Gallery Images"
        ordering = ['order', '-created_at']

class NewsArticle(models.Model):
    TAG_CHOICES = [
        ('Announcement', 'Announcement'),
        ('Voting', 'Voting'),
        ('Academy', 'Academy'),
        ('Event', 'Event'),
        ('Results', 'Results'),
    ]
    
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    excerpt = models.TextField()
    content = models.TextField(blank=True)
    tag = models.CharField(max_length=50, choices=TAG_CHOICES)
    image = models.ImageField(upload_to='news/', blank=True, null=True)
    published = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    published_date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.title
    
    class Meta:
        verbose_name_plural = "News Articles"
        ordering = ['-published_date', '-created_at']

class HallOfFame(models.Model):
    year = models.CharField(max_length=10)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=200)
    photo = models.ImageField(upload_to='hall_of_fame/', blank=True, null=True)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.year})"
    
    class Meta:
        verbose_name_plural = "Hall of Fame"
        ordering = ['-year', 'order']

class Partner(models.Model):
    TYPE_CHOICES = [
        ('presenting', 'Presenting Partner'),
        ('category', 'Category Partner'),
        ('media', 'Media Partner'),
        ('technology', 'Technology Partner'),
        ('community', 'Community Partner'),
    ]
    
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    logo = models.ImageField(upload_to='partners/', blank=True, null=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['order', 'name']