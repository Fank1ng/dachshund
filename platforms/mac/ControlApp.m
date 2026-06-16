#import <Cocoa/Cocoa.h>
#include <math.h>
#include <string.h>

static NSString *CPString(id value) {
    if (!value || value == NSNull.null) {
        return @"";
    }
    if ([value isKindOfClass:NSString.class]) {
        return value;
    }
    if ([value respondsToSelector:@selector(stringValue)]) {
        return [value stringValue];
    }
    return [value description] ?: @"";
}

static NSString *CPDisplayString(id value) {
    NSString *text = CPString(value);
    return text.length > 0 ? text : @"-";
}

static BOOL CPBool(id value) {
    if (!value || value == NSNull.null) {
        return NO;
    }
    if ([value respondsToSelector:@selector(boolValue)]) {
        return [value boolValue];
    }
    return NO;
}

static double CPDouble(id value) {
    if (!value || value == NSNull.null) {
        return 0;
    }
    if ([value respondsToSelector:@selector(doubleValue)]) {
        return [value doubleValue];
    }
    return 0;
}

static NSDictionary *CPDict(id value) {
    return [value isKindOfClass:NSDictionary.class] ? value : @{};
}

static NSArray *CPArray(id value) {
    return [value isKindOfClass:NSArray.class] ? value : @[];
}

static NSString *CPPrettyJSON(id object) {
    if (!object || ![NSJSONSerialization isValidJSONObject:object]) {
        return CPDisplayString(object);
    }
    NSData *data = [NSJSONSerialization dataWithJSONObject:object
                                                   options:NSJSONWritingPrettyPrinted
                                                     error:nil];
    return [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: CPDisplayString(object);
}

static NSString *CPRelativeTime(id epochValue) {
    NSTimeInterval epoch = CPDouble(epochValue);
    if (epoch <= 0) {
        return @"-";
    }
    NSDate *date = [NSDate dateWithTimeIntervalSince1970:epoch];
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.dateFormat = @"MM-dd HH:mm";
    return [formatter stringFromDate:date] ?: @"-";
}

static NSString *CPFullDateTime(id epochValue) {
    NSTimeInterval epoch = CPDouble(epochValue);
    if (epoch <= 0) {
        return @"-";
    }
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.dateFormat = @"yyyy-MM-dd HH:mm";
    return [formatter stringFromDate:[NSDate dateWithTimeIntervalSince1970:epoch]] ?: @"-";
}

static NSDate *CPDateFromString(NSString *dateString) {
    if (!dateString.length) {
        return nil;
    }
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.dateFormat = @"yyyy-MM-dd";
    return [formatter dateFromString:dateString];
}

static NSString *CPDateStringFromDate(NSDate *date) {
    if (!date) {
        return @"";
    }
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.dateFormat = @"yyyy-MM-dd";
    return [formatter stringFromDate:date] ?: @"";
}

static NSString *CPWeekStartForDateString(NSString *dateString) {
    NSDate *date = CPDateFromString(dateString);
    if (!date) {
        return @"";
    }
    NSCalendar *calendar = [NSCalendar.currentCalendar copy];
    calendar.firstWeekday = 2;
    NSDateComponents *components = [calendar components:NSCalendarUnitYearForWeekOfYear | NSCalendarUnitWeekOfYear fromDate:date];
    NSDate *weekStart = [calendar dateFromComponents:components];
    return CPDateStringFromDate(weekStart);
}

static NSInteger CPWeekdayIndexForDateString(NSString *dateString) {
    NSDate *date = CPDateFromString(dateString);
    if (!date) {
        return 0;
    }
    NSDateComponents *components = [NSCalendar.currentCalendar components:NSCalendarUnitWeekday fromDate:date];
    return MAX(0, (NSInteger)components.weekday - 1);
}

static NSString *CPExactTokenCount(id value) {
    return [NSString stringWithFormat:@"%.0f", CPDouble(value)];
}

static NSString *CPCompactTokenCount(id value) {
    double n = CPDouble(value);
    double absValue = fabs(n);
    if (absValue >= 1000000) {
        return [NSString stringWithFormat:@"%.1fM", n / 1000000.0];
    }
    if (absValue >= 1000) {
        return [NSString stringWithFormat:@"%.1fK", n / 1000.0];
    }
    return CPExactTokenCount(value);
}

static NSString *CPTokenUsagePeriodLabel(NSDictionary *row) {
    NSString *period = CPString(row[@"period_label"]);
    if (period.length) {
        return period;
    }
    NSString *date = CPString(row[@"date"]);
    if (date.length) {
        return date;
    }
    NSString *week = CPString(row[@"week_start"]);
    if (week.length) {
        return [NSString stringWithFormat:@"周起 %@", week];
    }
    return CPRelativeTime(row[@"at"]);
}

static NSString *CPTokenUsageTooltip(NSDictionary *row) {
    NSInteger requests = (NSInteger)CPDouble(row[@"requests"]);
    NSInteger unknown = (NSInteger)CPDouble(row[@"unknown_requests"]);
    NSInteger known = MAX(0, requests - unknown);
    NSInteger activeDays = (NSInteger)CPDouble(row[@"active_days"]);
    double cacheReadTokens = CPDouble(row[@"cache_read_tokens"]);
    double cacheCreationTokens = CPDouble(row[@"cache_creation_tokens"]);
    double cacheTokens = (cacheReadTokens || cacheCreationTokens)
        ? cacheReadTokens + cacheCreationTokens
        : MAX(CPDouble(row[@"cached_tokens"]), CPDouble(row[@"cache_tokens"]));
    BOOL cacheObserved = CPDouble(row[@"cache_tokens_observed_requests"]) > 0 || CPBool(row[@"cache_tokens_observed"]);
    BOOL reasoningObserved = CPDouble(row[@"reasoning_tokens_observed_requests"]) > 0 || CPBool(row[@"reasoning_tokens_observed"]);
    NSString *activeText = activeDays > 0 ? [NSString stringWithFormat:@"\n使用天数 %ld / 7", (long)activeDays] : @"";
    return [NSString stringWithFormat:@"%@\n总计 %@ tokens\n输入 %@ · 输出 %@\n缓存 %@\n推理 %@\n请求 %ld · 已知 %ld · 未知 %ld%@\n本地代理捕获口径",
            CPTokenUsagePeriodLabel(row),
            CPCompactTokenCount(row[@"total_tokens"]),
            CPCompactTokenCount(row[@"input_tokens"]),
            CPCompactTokenCount(row[@"output_tokens"]),
            cacheObserved ? CPCompactTokenCount(@(cacheTokens)) : @"-",
            reasoningObserved ? CPCompactTokenCount(row[@"reasoning_tokens"]) : @"-",
            (long)requests,
            (long)known,
            (long)unknown,
            activeText];
}

static BOOL CPIsDarkAppearance(NSAppearance *appearance) {
    NSAppearance *effective = appearance ?: NSApp.effectiveAppearance;
    NSString *match = [effective bestMatchFromAppearancesWithNames:@[
        NSAppearanceNameAqua,
        NSAppearanceNameDarkAqua,
    ]];
    return [match isEqualToString:NSAppearanceNameDarkAqua];
}

static NSColor *CPDynamicAquaColor(NSString *name, NSColor *lightColor, NSColor *darkColor) {
    if (@available(macOS 10.15, *)) {
        return [NSColor colorWithName:name dynamicProvider:^NSColor *(NSAppearance *appearance) {
            return CPIsDarkAppearance(appearance) ? darkColor : lightColor;
        }];
    }
    return CPIsDarkAppearance(NSApp.effectiveAppearance) ? darkColor : lightColor;
}

static NSColor *CPSidebarPanelBackgroundColor(void) {
    return CPDynamicAquaColor(@"CPSidebarPanelBackgroundColor",
                             [NSColor colorWithCalibratedWhite:0.98 alpha:0.86],
                             [NSColor colorWithCalibratedWhite:0.12 alpha:0.78]);
}

static NSColor *CPSidebarCardBackgroundColor(void) {
    return CPDynamicAquaColor(@"CPSidebarCardBackgroundColor",
                             [NSColor colorWithCalibratedWhite:1.00 alpha:0.64],
                             [NSColor colorWithCalibratedWhite:0.08 alpha:0.78]);
}

static NSColor *CPSidebarBorderColor(void) {
    return CPDynamicAquaColor(@"CPSidebarBorderColor",
                             [NSColor colorWithCalibratedWhite:0.00 alpha:0.18],
                             [NSColor colorWithCalibratedWhite:1.00 alpha:0.16]);
}

static NSColor *CPSettingsContentBackgroundColor(void) {
    return CPDynamicAquaColor(@"CPSettingsContentBackgroundColor",
                             [NSColor colorWithCalibratedWhite:0.985 alpha:1.0],
                             [NSColor colorWithCalibratedWhite:0.095 alpha:1.0]);
}

static NSColor *CPSettingsHeaderBackgroundColor(void) {
    return CPDynamicAquaColor(@"CPSettingsHeaderBackgroundColor",
                             [NSColor colorWithCalibratedWhite:0.985 alpha:1.0],
                             [NSColor colorWithCalibratedWhite:0.12 alpha:1.0]);
}

static NSNumber *CPJSONBool(BOOL value) {
    return [NSNumber numberWithBool:value];
}

static NSImage *CPMenuBarIconImage(void) {
    NSString *resourcePath = NSBundle.mainBundle.resourcePath ?: @"";
    NSArray<NSString *> *paths = @[
        [resourcePath stringByAppendingPathComponent:@"runtime/static/icons/dog-head.png"],
        [resourcePath stringByAppendingPathComponent:@"AppIcon.icns"],
    ];
    NSImage *source = nil;
    for (NSString *path in paths) {
        source = [[NSImage alloc] initWithContentsOfFile:path];
        if (source) {
            break;
        }
    }
    if (!source) {
        return nil;
    }

    NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(18, 18)];
    [image lockFocus];
    [NSGraphicsContext.currentContext setImageInterpolation:NSImageInterpolationHigh];
    NSSize size = source.size;
    CGFloat scale = MIN(18.0 / MAX(1, size.width), 18.0 / MAX(1, size.height));
    NSSize drawSize = NSMakeSize(size.width * scale, size.height * scale);
    NSRect drawRect = NSMakeRect((18 - drawSize.width) / 2.0,
                                 (18 - drawSize.height) / 2.0,
                                 drawSize.width,
                                 drawSize.height);
    [source drawInRect:drawRect
              fromRect:NSZeroRect
             operation:NSCompositingOperationSourceOver
              fraction:1.0
        respectFlipped:YES
                 hints:nil];
    [image unlockFocus];
    image.template = NO;
    image.accessibilityDescription = @"小腊肠";
    return image;
}

@class ControlWindowController;

@interface SettingsWindowController : NSObject <NSWindowDelegate>
@property(nonatomic, weak) ControlWindowController *owner;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSMutableDictionary<NSString *, NSControl *> *controls;
@property(nonatomic, strong) NSDictionary *configSnapshot;
@property(nonatomic, strong) NSDictionary *statusSnapshot;
@property(nonatomic, strong) NSDictionary *codexSnapshot;
@property(nonatomic, strong) NSDictionary *menubarLoginSnapshot;
@property(nonatomic, strong) NSTextField *statusLabel;
@property(nonatomic, strong) NSTextField *serviceLabel;
@property(nonatomic, strong) NSTextField *codexLabel;
@property(nonatomic, strong) NSTextField *baseURLLabel;
@property(nonatomic, strong) NSTextField *diagnosticsLabel;
@property(nonatomic, strong) NSTextField *summaryStatusLabel;
@property(nonatomic, strong) NSTextField *summaryAccountsLabel;
@property(nonatomic, strong) NSTextField *summaryVersionLabel;
@property(nonatomic, strong) NSTextField *overviewFocusServiceLabel;
@property(nonatomic, strong) NSTextField *overviewFocusAccountsLabel;
@property(nonatomic, strong) NSTextField *overviewFocusRepairLabel;
@property(nonatomic, strong) NSTextField *overviewFocusErrorsLabel;
@property(nonatomic, strong) NSTextField *overviewFocusQuotaLabel;
@property(nonatomic, strong) NSTextField *routingCurrentStrategyLabel;
@property(nonatomic, strong) NSTextField *routingCooldownLabel;
@property(nonatomic, strong) NSTextField *routingRefreshLabel;
@property(nonatomic, strong) NSTextField *routingWindowLabel;
@property(nonatomic, strong) NSTextField *codexModeSummaryLabel;
@property(nonatomic, strong) NSTextField *codexBaseSummaryLabel;
@property(nonatomic, strong) NSTextField *codexOpenAIBaseLabel;
@property(nonatomic, strong) NSTextField *codexChatGPTBaseLabel;
@property(nonatomic, strong) NSTextField *codexPortLabel;
@property(nonatomic, strong) NSTextField *codexRestartLabel;
@property(nonatomic, strong) NSTextField *advancedRestartImpactLabel;
@property(nonatomic, strong) NSTextField *advancedStreamImpactLabel;
@property(nonatomic, strong) NSTextField *advancedSessionImpactLabel;
@property(nonatomic, strong) NSTextField *advancedSaveImpactLabel;
@property(nonatomic, strong) NSTextField *runtimeDirLabel;
@property(nonatomic, strong) NSTextField *sourceDirLabel;
@property(nonatomic, strong) NSTextField *frontendVersionLabel;
@property(nonatomic, strong) NSTextField *runtimeVersionLabel;
@property(nonatomic, strong) NSTextField *proxyVersionLabel;
@property(nonatomic, strong) NSTextField *manifestLabel;
@property(nonatomic, strong) NSTextField *detailTitleLabel;
@property(nonatomic, strong) NSTextField *detailSubtitleLabel;
@property(nonatomic, strong) NSTextField *sidebarStatusLabel;
@property(nonatomic, strong) NSTextField *sidebarAccountsLabel;
@property(nonatomic, strong) NSTextField *sidebarVersionLabel;
@property(nonatomic, strong) NSSegmentedControl *proxyModeControl;
@property(nonatomic, strong) NSView *contentHost;
@property(nonatomic, strong) NSButton *restoreDefaultsButton;
@property(nonatomic, strong) NSButton *saveSettingsButton;
@property(nonatomic, strong) NSButton *menuBarLoginItemControl;
@property(nonatomic, strong) NSTextField *menuBarLoginItemLabel;
@property(nonatomic, strong) NSMutableArray<NSButton *> *settingsNavButtons;
@property(nonatomic, strong) NSMutableArray<NSImageView *> *settingsNavIconViews;
@property(nonatomic, strong) NSMutableArray<NSTextField *> *settingsNavTitleLabels;
@property(nonatomic, strong) NSMutableArray<NSScrollView *> *scrollViews;
@property(nonatomic, assign) NSInteger selectedSettingsIndex;
- (instancetype)initWithOwner:(ControlWindowController *)owner;
- (void)show;
- (void)seedInitialSnapshotsFromOwner;
- (void)refresh:(id)sender;
- (void)rebuildSettingsPagesSelectingIndex:(NSInteger)selected;
- (void)populateControls;
@end

@interface ControlWindowController : NSObject <NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) SettingsWindowController *settingsController;
@property(nonatomic, strong) NSSplitView *splitView;
@property(nonatomic, strong) NSStackView *sidebarStack;
@property(nonatomic, strong) NSStackView *toolbarStack;
@property(nonatomic, strong) NSStackView *contentStack;
@property(nonatomic, strong) NSStackView *inspectorStack;
@property(nonatomic, strong) NSTextField *titleLabel;
@property(nonatomic, strong) NSTextField *subtitleLabel;
@property(nonatomic, strong) NSTextField *footerStatusLabel;
@property(nonatomic, strong) NSTextField *sidebarStatusLabel;
@property(nonatomic, strong) NSTextView *outputView;
@property(nonatomic, strong) NSTableView *accountTable;
@property(nonatomic, strong) NSMutableArray<NSButton *> *buttons;
@property(nonatomic, strong) NSMutableArray<NSButton *> *navButtons;
@property(nonatomic, strong) NSMutableArray<NSImageView *> *navIconViews;
@property(nonatomic, strong) NSMutableArray<NSTextField *> *navTitleLabels;
@property(nonatomic, strong) NSArray<NSDictionary *> *accounts;
@property(nonatomic, strong) NSDictionary *statusSnapshot;
@property(nonatomic, strong) NSDictionary *quotaSnapshot;
@property(nonatomic, strong) NSDictionary *tokenUsageSnapshot;
@property(nonatomic, strong) NSArray<NSDictionary *> *tokenUsageEvents;
@property(nonatomic, copy) NSString *activeSection;
@property(nonatomic, copy) NSString *selectedAccountName;
@property(nonatomic, copy) NSString *appBundlePath;
@property(nonatomic, copy) NSString *frontendVersion;
@property(nonatomic, copy) NSString *resourceRuntimeDir;
@property(nonatomic, copy) NSString *runtimeDir;
@property(nonatomic, copy) NSString *resultPath;
@property(nonatomic, copy) NSString *logPath;
@property(nonatomic, strong) NSTimer *refreshTimer;
@property(nonatomic, assign) BOOL busy;
@property(nonatomic, assign) BOOL refreshInFlight;
@property(nonatomic, assign) BOOL compactInspector;
@property(nonatomic, assign) BOOL runtimeReady;
@property(nonatomic, assign) NSInteger tokenUsageMode;
- (void)showSettings:(id)sender;
- (void)repairAction:(id)sender;
- (void)openCodexAction:(id)sender;
- (void)openWebAction:(id)sender;
- (void)openLogAction:(id)sender;
- (void)openResultAction:(id)sender;
- (void)showPathsAction:(id)sender;
- (void)startRuntimeInitialization;
- (void)startHeadlessRuntimeInitializationWithCompletion:(void (^)(BOOL ok))completion;
- (NSDictionary *)snapshotPayloadRefreshingQuota:(BOOL)refreshQuota
                              quotaRefreshResult:(NSDictionary **)quotaRefreshResult
                                     proxyOnline:(BOOL *)proxyOnline;
- (void)applySnapshotPayload:(NSDictionary *)payload;
- (void)applySilentSnapshotPayload:(NSDictionary *)payload;
- (NSDictionary *)runPythonJSONSync:(NSArray<NSString *> *)args rawText:(NSString **)rawText;
- (id)fetchJSONPath:(NSString *)path method:(NSString *)method timeout:(NSTimeInterval)timeout;
- (void)appendLog:(NSString *)text;
- (void)refreshSnapshots:(id)sender;
- (BOOL)shouldShowSetupCard;
- (BOOL)hasRuntimeManifestMismatch;
- (BOOL)hasVersionMismatch;
- (BOOL)hasUsageStorageMismatch;
- (NSView *)constrainedContentView:(NSView *)content width:(CGFloat)width;
- (NSView *)metricsRow;
- (NSView *)totalQuotaCard;
- (NSView *)tokenStatsCard;
- (NSView *)tokenBarChartCard;
- (NSView *)tokenHeatmapCard;
- (NSButton *)tokenHeatmapModeButtonWithTitle:(NSString *)title tag:(NSInteger)tag;
- (NSView *)recentRequestsCard;
- (NSView *)accountManagementCard;
- (NSView *)accountQuickActionsCard;
- (NSView *)quotaCard;
- (NSView *)selectionExplanationCard;
- (NSView *)proxyConfirmationCard;
- (NSView *)setupChecklistCard;
- (NSView *)runtimeSyncCard;
- (NSView *)configCardsRow;
- (NSView *)strategyCard;
- (NSView *)updateDiagnosticsCard;
- (NSView *)pathsCard;
- (NSView *)logCardWithHeight:(CGFloat)height actions:(BOOL)actions;
- (double)quotaRemainingForAccountName:(NSString *)name weekly:(BOOL)weekly;
- (NSDictionary *)quotaSummary;
- (NSString *)quotaTotalTextForWeekly:(BOOL)weekly;
- (NSView *)quotaLaneWithTitle:(NSString *)title captionText:(NSString *)captionText progress:(double)progress color:(NSColor *)color;
- (NSImage *)symbolImageNamed:(NSString *)name;
@end

@interface CPFlippedStackView : NSStackView
@end

@interface CPFlippedView : NSView
@end

@interface CPThemedView : NSView
@property(nonatomic, strong) NSColor *cpBackgroundColor;
@property(nonatomic, strong) NSColor *cpBorderColor;
@property(nonatomic, strong) NSColor *cpShadowColor;
@end

@interface CPQuotaRingView : NSView
@property(nonatomic, assign) double progress;
@property(nonatomic, copy) NSString *centerText;
@property(nonatomic, strong) NSColor *ringColor;
@end

@interface CPBarChartView : NSView
@property(nonatomic, strong) NSArray<NSDictionary *> *rows;
@property(nonatomic, strong) NSMutableArray<NSValue *> *hitRects;
@property(nonatomic, assign) NSInteger hoverIndex;
@property(nonatomic, strong) NSTrackingArea *cpTrackingArea;
@end

@interface CPHeatmapView : NSView
@property(nonatomic, strong) NSArray<NSDictionary *> *rows;
@property(nonatomic, strong) NSMutableArray<NSValue *> *hitRects;
@property(nonatomic, strong) NSMutableArray<NSNumber *> *hitIndexes;
@property(nonatomic, assign) NSInteger hoverIndex;
@property(nonatomic, strong) NSTrackingArea *cpTrackingArea;
@property(nonatomic, assign) CGFloat cellMaxSize;
@property(nonatomic, assign) CGFloat cellMinSize;
@property(nonatomic, assign) CGFloat cellGap;
@property(nonatomic, assign) CGFloat monthLabelFontSize;
@end

@implementation CPFlippedStackView
- (BOOL)isFlipped {
    return YES;
}
@end

@implementation CPFlippedView
- (BOOL)isFlipped {
    return YES;
}
@end

@implementation CPThemedView
- (void)setCpBackgroundColor:(NSColor *)cpBackgroundColor {
    _cpBackgroundColor = cpBackgroundColor;
    [self cpApplyThemeColors];
}

- (void)setCpBorderColor:(NSColor *)cpBorderColor {
    _cpBorderColor = cpBorderColor;
    [self cpApplyThemeColors];
}

- (void)setCpShadowColor:(NSColor *)cpShadowColor {
    _cpShadowColor = cpShadowColor;
    [self cpApplyThemeColors];
}

- (CGColorRef)cpCGColorForColor:(NSColor *)color {
    if (!color) {
        return nil;
    }
    __block CGColorRef cgColor = nil;
    NSAppearance *appearance = self.effectiveAppearance ?: NSApp.effectiveAppearance;
    [appearance performAsCurrentDrawingAppearance:^{
        NSColor *rgb = [color colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace] ?: color;
        if (rgb.CGColor) {
            cgColor = CGColorRetain(rgb.CGColor);
        }
    }];
    return cgColor ? (CGColorRef)CFAutorelease(cgColor) : nil;
}

- (void)cpApplyThemeColors {
    if (!self.layer) {
        self.wantsLayer = YES;
    }
    self.layer.backgroundColor = [self cpCGColorForColor:self.cpBackgroundColor];
    self.layer.borderColor = [self cpCGColorForColor:self.cpBorderColor];
    self.layer.shadowColor = [self cpCGColorForColor:self.cpShadowColor ?: NSColor.blackColor];
}

- (void)viewDidChangeEffectiveAppearance {
    [super viewDidChangeEffectiveAppearance];
    [self cpApplyThemeColors];
}
@end

@implementation CPQuotaRingView
- (BOOL)isFlipped { return YES; }
- (void)setProgress:(double)progress {
    _progress = MAX(0, MIN(1, progress));
    self.needsDisplay = YES;
}
- (void)setCenterText:(NSString *)centerText {
    _centerText = [centerText copy];
    self.needsDisplay = YES;
}
- (void)setRingColor:(NSColor *)ringColor {
    _ringColor = ringColor;
    self.needsDisplay = YES;
}
- (void)drawRect:(NSRect)dirtyRect {
    [super drawRect:dirtyRect];
    CGFloat side = MIN(self.bounds.size.width, self.bounds.size.height) - 14;
    NSRect rect = NSMakeRect((self.bounds.size.width - side) / 2, (self.bounds.size.height - side) / 2, side, side);
    NSBezierPath *track = [NSBezierPath bezierPathWithOvalInRect:rect];
    track.lineWidth = 9;
    [[NSColor.separatorColor colorWithAlphaComponent:0.45] setStroke];
    [track stroke];

    NSBezierPath *arc = [NSBezierPath bezierPath];
    CGFloat radius = side / 2;
    NSPoint center = NSMakePoint(NSMidX(rect), NSMidY(rect));
    [arc appendBezierPathWithArcWithCenter:center radius:radius startAngle:-90 endAngle:-90 + (360 * self.progress) clockwise:NO];
    arc.lineWidth = 9;
    arc.lineCapStyle = NSLineCapStyleRound;
    [(self.ringColor ?: NSColor.controlAccentColor) setStroke];
    [arc stroke];

    NSString *text = self.centerText.length ? self.centerText : @"-";
    NSDictionary *attrs = @{
        NSFontAttributeName: [NSFont monospacedDigitSystemFontOfSize:22 weight:NSFontWeightSemibold],
        NSForegroundColorAttributeName: self.ringColor ?: NSColor.controlAccentColor,
    };
    NSSize size = [text sizeWithAttributes:attrs];
    [text drawAtPoint:NSMakePoint(center.x - size.width / 2, center.y - size.height / 2) withAttributes:attrs];
}
@end

@implementation CPBarChartView
- (BOOL)isFlipped { return YES; }
- (void)setRows:(NSArray<NSDictionary *> *)rows {
    _rows = rows;
    self.hoverIndex = -1;
    self.needsDisplay = YES;
}
- (void)updateTrackingAreas {
    [super updateTrackingAreas];
    if (self.cpTrackingArea) {
        [self removeTrackingArea:self.cpTrackingArea];
    }
    self.cpTrackingArea = [[NSTrackingArea alloc] initWithRect:self.bounds
                                                       options:(NSTrackingMouseMoved | NSTrackingMouseEnteredAndExited | NSTrackingActiveInKeyWindow | NSTrackingInVisibleRect)
                                                         owner:self
                                                      userInfo:nil];
    [self addTrackingArea:self.cpTrackingArea];
}
- (void)mouseMoved:(NSEvent *)event {
    NSPoint point = [self convertPoint:event.locationInWindow fromView:nil];
    NSInteger index = -1;
    for (NSInteger i = 0; i < self.hitRects.count; i++) {
        if (NSPointInRect(point, self.hitRects[i].rectValue)) {
            index = i;
            break;
        }
    }
    if (index != self.hoverIndex) {
        self.hoverIndex = index;
        self.toolTip = index >= 0 && index < self.rows.count ? CPTokenUsageTooltip(self.rows[index]) : nil;
        self.needsDisplay = YES;
    }
}
- (void)mouseExited:(NSEvent *)event {
    self.hoverIndex = -1;
    self.toolTip = nil;
    self.needsDisplay = YES;
}
- (void)drawRect:(NSRect)dirtyRect {
    [super drawRect:dirtyRect];
    NSArray *rows = self.rows ?: @[];
    self.hitRects = [NSMutableArray array];
    if (!rows.count) {
        return;
    }
    double maxValue = 1;
    for (NSDictionary *row in rows) {
        maxValue = MAX(maxValue, CPDouble(row[@"total_tokens"]));
    }
    CGFloat horizontalInset = 10;
    CGFloat topInset = 4;
    CGFloat bottomInset = 0;
    CGFloat baselineY = MAX(topInset + 1, self.bounds.size.height - bottomInset);
    CGFloat chartHeight = MAX(1, baselineY - topInset);
    CGFloat availableWidth = MAX(1, self.bounds.size.width - (horizontalInset * 2));
    CGFloat gap = 3;
    CGFloat barWidth = MAX(3, (availableWidth - gap * (rows.count - 1)) / rows.count);
    for (NSInteger i = 0; i < rows.count; i++) {
        NSDictionary *row = rows[i];
        double value = CPDouble(row[@"total_tokens"]);
        CGFloat height = value > 0 ? MAX(2, chartHeight * value / maxValue) : 2;
        height = MIN(height, chartHeight);
        CGFloat x = horizontalInset + i * (barWidth + gap);
        NSRect barRect = NSMakeRect(x, baselineY - height, barWidth, height);
        [self.hitRects addObject:[NSValue valueWithRect:barRect]];
        NSBezierPath *bar = [NSBezierPath bezierPathWithRoundedRect:barRect xRadius:2 yRadius:2];
        BOOL hovered = i == self.hoverIndex;
        [[NSColor.controlAccentColor colorWithAlphaComponent:hovered ? 0.98 : (value > 0 ? 0.82 : 0.16)] setFill];
        [bar fill];
        if (hovered) {
            [NSColor.labelColor setStroke];
            bar.lineWidth = 1.4;
            [bar stroke];
        }
    }
}
@end

@implementation CPHeatmapView
- (BOOL)isFlipped { return YES; }
- (instancetype)initWithFrame:(NSRect)frameRect {
    self = [super initWithFrame:frameRect];
    if (self) {
        _cellMaxSize = 8;
        _cellMinSize = 4;
        _cellGap = 0.2;
        _monthLabelFontSize = 9;
    }
    return self;
}
- (void)setRows:(NSArray<NSDictionary *> *)rows {
    _rows = rows;
    self.hoverIndex = -1;
    self.needsDisplay = YES;
}
- (void)updateTrackingAreas {
    [super updateTrackingAreas];
    if (self.cpTrackingArea) {
        [self removeTrackingArea:self.cpTrackingArea];
    }
    self.cpTrackingArea = [[NSTrackingArea alloc] initWithRect:self.bounds
                                                       options:(NSTrackingMouseMoved | NSTrackingMouseEnteredAndExited | NSTrackingActiveInKeyWindow | NSTrackingInVisibleRect)
                                                         owner:self
                                                      userInfo:nil];
    [self addTrackingArea:self.cpTrackingArea];
}
- (void)mouseMoved:(NSEvent *)event {
    NSPoint point = [self convertPoint:event.locationInWindow fromView:nil];
    NSInteger index = -1;
    for (NSInteger i = 0; i < self.hitRects.count; i++) {
        if (NSPointInRect(point, self.hitRects[i].rectValue)) {
            index = i < self.hitIndexes.count ? self.hitIndexes[i].integerValue : i;
            break;
        }
    }
    if (index != self.hoverIndex) {
        self.hoverIndex = index;
        self.toolTip = index >= 0 && index < self.rows.count ? CPTokenUsageTooltip(self.rows[index]) : nil;
        self.needsDisplay = YES;
    }
}
- (void)mouseExited:(NSEvent *)event {
    self.hoverIndex = -1;
    self.toolTip = nil;
    self.needsDisplay = YES;
}
- (NSInteger)weekdayForDateString:(NSString *)dateString {
    return CPWeekdayIndexForDateString(dateString);
}
- (NSString *)monthLabelForDateString:(NSString *)dateString {
    if (dateString.length < 7) {
        return @"";
    }
    NSInteger month = [[dateString substringWithRange:NSMakeRange(5, 2)] integerValue];
    return month > 0 ? [NSString stringWithFormat:@"%ld月", (long)month] : @"";
}
- (double)heatValueForRow:(NSDictionary *)row {
    id heatValue = row[@"heat_value"];
    if (heatValue && heatValue != NSNull.null) {
        return CPDouble(heatValue);
    }
    return CPDouble(row[@"total_tokens"]);
}
- (double)heatMaxValueForRows:(NSArray<NSDictionary *> *)rows {
    double maxValue = 1;
    BOOL hasFixedMax = NO;
    for (NSDictionary *row in rows) {
        id heatMax = row[@"heat_max"];
        if (heatMax && heatMax != NSNull.null) {
            hasFixedMax = YES;
            maxValue = MAX(maxValue, CPDouble(heatMax));
        }
    }
    if (hasFixedMax) {
        return maxValue;
    }
    for (NSDictionary *row in rows) {
        maxValue = MAX(maxValue, [self heatValueForRow:row]);
    }
    return maxValue;
}
- (void)drawRect:(NSRect)dirtyRect {
    [super drawRect:dirtyRect];
    NSArray *rows = self.rows ?: @[];
    self.hitRects = [NSMutableArray array];
    self.hitIndexes = [NSMutableArray array];
    if (!rows.count) {
        return;
    }
    double maxValue = [self heatMaxValueForRows:rows];
    NSInteger rowCount = 7;
    NSInteger columns = 53;
    NSInteger leading = [self weekdayForDateString:CPString(rows.firstObject[@"date"])];
    NSInteger latestSlot = leading + rows.count - 1;
    NSInteger latestWeekday = [self weekdayForDateString:CPString(rows.lastObject[@"date"])];
    NSInteger firstVisibleSlot = latestSlot - ((columns - 1) * rowCount + latestWeekday);
    CGFloat horizontalInset = 0;
    CGFloat monthLabelHeight = MAX(12, (self.monthLabelFontSize > 0 ? self.monthLabelFontSize : 9) + 5);
    CGFloat topInset = 0;
    CGFloat gap = self.cellGap > 0 ? self.cellGap : 0.2;
    CGFloat availableWidth = MAX(1, self.bounds.size.width - horizontalInset * 2 - gap * MAX(0, columns - 1));
    CGFloat availableHeight = MAX(1, self.bounds.size.height - monthLabelHeight - topInset - gap * MAX(0, rowCount - 1));
    CGFloat maxCell = self.cellMaxSize > 0 ? self.cellMaxSize : 8;
    CGFloat minCell = self.cellMinSize > 0 ? self.cellMinSize : 4;
    CGFloat cell = MIN(maxCell, MIN(availableWidth / columns, availableHeight / rowCount));
    cell = MAX(minCell, cell);
    CGFloat gridWidth = columns * cell + MAX(0, columns - 1) * gap;
    CGFloat xOrigin = horizontalInset + MAX(0, (self.bounds.size.width - horizontalInset * 2 - gridWidth) / 2.0);
    CGFloat gridHeight = rowCount * cell + MAX(0, rowCount - 1) * gap;
    CGFloat labelY = MAX(topInset + gridHeight + 2, self.bounds.size.height - monthLabelHeight);
    CGFloat yOrigin = MAX(topInset, labelY - 3 - gridHeight);
    NSMutableDictionary<NSNumber *, NSString *> *monthLabels = [NSMutableDictionary dictionary];
    for (NSInteger i = 0; i < rows.count; i++) {
        NSDictionary *row = rows[i];
        NSInteger slot = leading + i - firstVisibleSlot;
        if (slot < 0 || slot >= columns * rowCount) {
            continue;
        }
        NSInteger col = slot / 7;
        NSInteger line = slot % 7;
        CGFloat x = xOrigin + col * (cell + gap);
        CGFloat y = yOrigin + line * (cell + gap);
        NSString *date = CPString(row[@"date"]);
        if (date.length >= 10 && [[date substringFromIndex:8] isEqualToString:@"01"]) {
            monthLabels[@(col)] = [self monthLabelForDateString:date];
        }
        NSRect cellRect = NSMakeRect(x, y, cell, cell);
        [self.hitRects addObject:[NSValue valueWithRect:cellRect]];
        [self.hitIndexes addObject:@(i)];
        double ratio = maxValue <= 0 ? 0 : [self heatValueForRow:row] / maxValue;
        BOOL hovered = i == self.hoverIndex;
        NSColor *color = ratio <= 0
            ? [NSColor.separatorColor colorWithAlphaComponent:0.35]
            : [NSColor.controlAccentColor colorWithAlphaComponent:hovered ? 0.95 : (0.25 + 0.65 * ratio)];
        [color setFill];
        NSBezierPath *cellPath = [NSBezierPath bezierPathWithRoundedRect:cellRect xRadius:2 yRadius:2];
        [cellPath fill];
        if (hovered) {
            [NSColor.labelColor setStroke];
            cellPath.lineWidth = 1.2;
            [cellPath stroke];
        }
    }
    if (monthLabels.count) {
        NSDictionary *attrs = @{
            NSFontAttributeName: [NSFont systemFontOfSize:(self.monthLabelFontSize > 0 ? self.monthLabelFontSize : 9) weight:NSFontWeightMedium],
            NSForegroundColorAttributeName: NSColor.secondaryLabelColor,
        };
        for (NSNumber *colNumber in monthLabels) {
            NSInteger col = colNumber.integerValue;
            NSString *label = monthLabels[colNumber];
            CGFloat x = xOrigin + col * (cell + gap);
            [label drawAtPoint:NSMakePoint(x, labelY) withAttributes:attrs];
        }
    }
}
@end

@implementation ControlWindowController

- (instancetype)init {
    self = [super init];
    if (!self) {
        return nil;
    }
    NSBundle *bundle = NSBundle.mainBundle;
    _appBundlePath = bundle.bundlePath;
    _frontendVersion = CPDisplayString(bundle.infoDictionary[@"CFBundleShortVersionString"]);
    _resourceRuntimeDir = [bundle.resourceURL URLByAppendingPathComponent:@"runtime"].path;
    _runtimeDir = [@"~/Library/Application Support/xiaolachang" stringByExpandingTildeInPath];
    _resultPath = [_runtimeDir stringByAppendingPathComponent:@"control-result.txt"];
    _logPath = [_runtimeDir stringByAppendingPathComponent:@"control-app.log"];
    _buttons = [NSMutableArray array];
    _navButtons = [NSMutableArray array];
    _navIconViews = [NSMutableArray array];
    _navTitleLabels = [NSMutableArray array];
    _accounts = @[];
    _statusSnapshot = @{};
    _quotaSnapshot = @{};
    _tokenUsageSnapshot = @{};
    _tokenUsageEvents = @[];
    _activeSection = @"overview";
    _tokenUsageMode = 0;
    return self;
}

- (void)show {
    NSRect frame = NSMakeRect(0, 0, 600, 460);
    self.window = [[NSWindow alloc] initWithContentRect:frame
                                             styleMask:(NSWindowStyleMaskTitled |
                                                        NSWindowStyleMaskClosable |
                                                        NSWindowStyleMaskMiniaturizable |
                                                        NSWindowStyleMaskFullSizeContentView)
                                               backing:NSBackingStoreBuffered
                                                 defer:NO];
    self.window.title = @"";
    self.window.contentMinSize = NSMakeSize(600, 460);
    self.window.contentMaxSize = NSMakeSize(600, 460);
    self.window.minSize = self.window.frame.size;
    self.window.maxSize = self.window.frame.size;
    self.window.delegate = self;
    self.window.titleVisibility = NSWindowTitleHidden;
    self.window.titlebarAppearsTransparent = YES;
    self.window.movableByWindowBackground = YES;
    [self.window center];

    CPThemedView *root = [[CPThemedView alloc] initWithFrame:frame];
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    root.wantsLayer = YES;
    root.cpBackgroundColor = NSColor.windowBackgroundColor;
    self.window.contentView = root;

    NSView *sidebar = [[NSView alloc] init];
    sidebar.translatesAutoresizingMaskIntoConstraints = NO;
    [root addSubview:sidebar];
    [self buildSidebarInView:sidebar];

    NSView *mainView = [[NSView alloc] init];
    mainView.translatesAutoresizingMaskIntoConstraints = NO;
    [root addSubview:mainView];
    [self buildMainView:mainView];
    [NSLayoutConstraint activateConstraints:@[
        [sidebar.leadingAnchor constraintEqualToAnchor:root.leadingAnchor],
        [sidebar.topAnchor constraintEqualToAnchor:root.topAnchor],
        [sidebar.bottomAnchor constraintEqualToAnchor:root.bottomAnchor],
        [sidebar.widthAnchor constraintEqualToConstant:118],
        [mainView.leadingAnchor constraintEqualToAnchor:sidebar.trailingAnchor],
        [mainView.trailingAnchor constraintEqualToAnchor:root.trailingAnchor],
        [mainView.topAnchor constraintEqualToAnchor:root.topAnchor],
        [mainView.bottomAnchor constraintEqualToAnchor:root.bottomAnchor],
    ]];

    [self.window makeKeyAndOrderFront:nil];
    [self.window.contentView layoutSubtreeIfNeeded];
    [self positionTrafficLightButtons];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self positionTrafficLightButtons];
    });
    [NSApp activateIgnoringOtherApps:YES];
    [self appendLog:@"控制台已启动。原生 App 会优先读取本地代理 API，代理离线时回退到本地账号扫描。"];
    [NSDistributedNotificationCenter.defaultCenter addObserver:self
                                                      selector:@selector(systemAppearanceChanged:)
                                                          name:@"AppleInterfaceThemeChangedNotification"
                                                        object:nil];
    [self startRuntimeInitialization];
    self.refreshTimer = [NSTimer scheduledTimerWithTimeInterval:15
                                                         target:self
                                                       selector:@selector(autoRefreshSnapshots:)
                                                       userInfo:nil
                                                        repeats:YES];
}

- (void)startRuntimeInitialization {
    if (self.footerStatusLabel) {
        self.footerStatusLabel.stringValue = @"正在准备运行目录...";
    }
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *error = nil;
        BOOL ok = [self ensureRuntimeReady:&error];
        dispatch_async(dispatch_get_main_queue(), ^{
            self.runtimeReady = ok;
            if (!ok) {
                [self appendLog:[NSString stringWithFormat:@"运行目录初始化失败：%@", error.localizedDescription]];
                if (self.footerStatusLabel) {
                    self.footerStatusLabel.stringValue = @"运行目录初始化失败";
                }
                return;
            }
            [self appendLog:@"运行目录已就绪。"];
            [self refreshSnapshots:nil];
        });
    });
}

- (void)startHeadlessRuntimeInitializationWithCompletion:(void (^)(BOOL ok))completion {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *error = nil;
        BOOL ok = [self ensureRuntimeReady:&error];
        dispatch_async(dispatch_get_main_queue(), ^{
            self.runtimeReady = ok;
            if (!ok) {
                [self appendLog:[NSString stringWithFormat:@"运行目录初始化失败：%@", error.localizedDescription]];
            }
            if (completion) {
                completion(ok);
            }
        });
    });
}

- (void)windowWillClose:(NSNotification *)notification {
    [NSDistributedNotificationCenter.defaultCenter removeObserver:self];
    [self.refreshTimer invalidate];
    self.refreshTimer = nil;
}

- (void)systemAppearanceChanged:(NSNotification *)notification {
    dispatch_async(dispatch_get_main_queue(), ^{
        [self updateNavigationSelection];
        [self renderActiveSection];
        [self positionTrafficLightButtons];
    });
}

#pragma mark - Layout

- (void)positionTrafficLightButtons {
    NSButton *closeButton = [self.window standardWindowButton:NSWindowCloseButton];
    NSButton *miniaturizeButton = [self.window standardWindowButton:NSWindowMiniaturizeButton];
    NSButton *zoomButton = [self.window standardWindowButton:NSWindowZoomButton];
    if (!closeButton || !miniaturizeButton || !zoomButton || !self.toolbarStack) {
        return;
    }
    NSView *buttonSuperview = closeButton.superview;
    if (!buttonSuperview) {
        return;
    }
    [self.window.contentView layoutSubtreeIfNeeded];
    [self.toolbarStack layoutSubtreeIfNeeded];
    NSPoint toolbarCenter = NSMakePoint(NSMidX(self.toolbarStack.bounds), NSMidY(self.toolbarStack.bounds));
    NSPoint windowPoint = [self.toolbarStack convertPoint:toolbarCenter toView:nil];
    NSPoint targetPoint = [buttonSuperview convertPoint:windowPoint fromView:nil];
    CGFloat targetCenterY = targetPoint.y;
    NSPoint navIconLeftInContent = NSMakePoint(20, 0);
    NSPoint navIconLeftInWindow = [self.window.contentView convertPoint:navIconLeftInContent toView:nil];
    NSPoint navIconLeftInButtonSuperview = [buttonSuperview convertPoint:navIconLeftInWindow fromView:nil];
    CGFloat deltaX = round(navIconLeftInButtonSuperview.x - closeButton.frame.origin.x);
    for (NSButton *button in @[closeButton, miniaturizeButton, zoomButton]) {
        NSRect frame = button.frame;
        frame.origin.x = round(frame.origin.x + deltaX);
        frame.origin.y = round(targetCenterY - (frame.size.height / 2.0));
        button.frame = frame;
    }
}

- (void)buildSidebarInView:(NSView *)sidebar {
    NSVisualEffectView *panel = [[NSVisualEffectView alloc] init];
    panel.translatesAutoresizingMaskIntoConstraints = NO;
    panel.wantsLayer = YES;
    panel.material = NSVisualEffectMaterialSidebar;
    panel.blendingMode = NSVisualEffectBlendingModeBehindWindow;
    panel.state = NSVisualEffectStateActive;
    panel.layer.cornerRadius = 14;
    panel.layer.masksToBounds = NO;
    panel.layer.backgroundColor = [CPSidebarPanelBackgroundColor() colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace].CGColor;
    panel.layer.borderColor = [CPSidebarBorderColor() colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace].CGColor;
    panel.layer.borderWidth = 0.6;
    panel.layer.shadowColor = NSColor.blackColor.CGColor;
    panel.layer.shadowOpacity = 0.08;
    panel.layer.shadowOffset = CGSizeMake(0, -1);
    panel.layer.shadowRadius = 8;
    [sidebar addSubview:panel];
    [NSLayoutConstraint activateConstraints:@[
        [panel.leadingAnchor constraintEqualToAnchor:sidebar.leadingAnchor constant:2],
        [panel.trailingAnchor constraintEqualToAnchor:sidebar.trailingAnchor constant:-2],
        [panel.topAnchor constraintEqualToAnchor:sidebar.topAnchor constant:2],
        [panel.bottomAnchor constraintEqualToAnchor:sidebar.bottomAnchor constant:-2],
    ]];

    self.sidebarStack = [[NSStackView alloc] init];
    self.sidebarStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    self.sidebarStack.alignment = NSLayoutAttributeLeading;
    self.sidebarStack.spacing = 6;
    self.sidebarStack.edgeInsets = NSEdgeInsetsMake(0, 0, 0, 0);
    self.sidebarStack.translatesAutoresizingMaskIntoConstraints = NO;
    [panel addSubview:self.sidebarStack];
    [self pinView:self.sidebarStack toView:panel insets:NSEdgeInsetsMake(44, 8, 12, 8)];

    [self addSpacerToStack:self.sidebarStack height:4];

    NSArray<NSDictionary *> *items = @[
        @{@"id": @"overview", @"title": @"总览", @"symbol": @"chart.pie"},
        @{@"id": @"accounts", @"title": @"账号", @"symbol": @"person.2"},
        @{@"id": @"config", @"title": @"配置", @"symbol": @"slider.horizontal.3"},
        @{@"id": @"logs", @"title": @"日志", @"symbol": @"terminal"},
    ];
    NSInteger index = 0;
    for (NSDictionary *item in items) {
        NSButton *button = [self navigationButtonWithTitle:item[@"title"] symbol:item[@"symbol"] tag:index];
        [self.sidebarStack addArrangedSubview:button];
        [self.navButtons addObject:button];
        index += 1;
    }

    NSView *flex = [[NSView alloc] init];
    flex.translatesAutoresizingMaskIntoConstraints = NO;
    [self.sidebarStack addArrangedSubview:flex];
    [flex.heightAnchor constraintGreaterThanOrEqualToConstant:90].active = YES;

    NSView *statusCard = [self cardViewWithBackground:CPSidebarCardBackgroundColor()];
    statusCard.translatesAutoresizingMaskIntoConstraints = NO;
    statusCard.layer.cornerRadius = 9;
    [statusCard.widthAnchor constraintEqualToConstant:98].active = YES;
    [statusCard.heightAnchor constraintEqualToConstant:66].active = YES;
    NSStackView *statusStack = [[NSStackView alloc] init];
    statusStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    statusStack.spacing = 4;
    statusStack.edgeInsets = NSEdgeInsetsMake(9, 9, 9, 9);
    statusStack.translatesAutoresizingMaskIntoConstraints = NO;
    [statusCard addSubview:statusStack];
    [self pinView:statusStack toView:statusCard insets:NSEdgeInsetsMake(9, 9, 9, 9)];

    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.spacing = 6;
    [row addArrangedSubview:[self statusDotWithColor:NSColor.systemGrayColor]];
    [row addArrangedSubview:[self labelWithText:@"后台服务" font:[NSFont systemFontOfSize:10 weight:NSFontWeightSemibold] color:NSColor.labelColor]];
    [statusStack addArrangedSubview:row];
    self.sidebarStatusLabel = [self labelWithText:@"读取中..." font:[NSFont systemFontOfSize:9 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
    self.sidebarStatusLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    [statusStack addArrangedSubview:self.sidebarStatusLabel];
    [self.sidebarStack addArrangedSubview:statusCard];

    [self updateNavigationSelection];
}

- (void)buildMainView:(NSView *)mainView {
    NSStackView *rootStack = [[NSStackView alloc] init];
    rootStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    rootStack.alignment = NSLayoutAttributeWidth;
    rootStack.spacing = 0;
    rootStack.translatesAutoresizingMaskIntoConstraints = NO;
    [mainView addSubview:rootStack];
    [self pinView:rootStack toView:mainView insets:NSEdgeInsetsMake(12, 16, 10, 16)];

    NSView *header = [[NSView alloc] init];
    header.translatesAutoresizingMaskIntoConstraints = NO;

    self.titleLabel = [self labelWithText:@"账号池代理" font:[NSFont systemFontOfSize:23 weight:NSFontWeightBold] color:NSColor.labelColor];
    self.subtitleLabel = [self labelWithText:@"正在读取本机代理状态..." font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];

    self.toolbarStack = [[NSStackView alloc] init];
    self.toolbarStack.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    self.toolbarStack.spacing = 6;
    self.toolbarStack.alignment = NSLayoutAttributeCenterY;
    self.toolbarStack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.toolbarStack addArrangedSubview:[self actionButtonWithTitle:@"刷新" symbol:@"arrow.clockwise" selector:@selector(refreshSnapshots:) primary:NO]];
    NSButton *repairButton = [self actionButtonWithTitle:@"启动/修复" symbol:@"play.circle.fill" selector:@selector(repairAction:) primary:YES];
    repairButton.toolTip = @"启动、修复或更新后台代理服务";
    [self.toolbarStack addArrangedSubview:repairButton];
    [self.toolbarStack addArrangedSubview:[self actionButtonWithTitle:@"打开 Codex" symbol:@"arrow.up.forward.app" selector:@selector(openCodexAction:) primary:NO]];
    [header addSubview:self.toolbarStack];
    [NSLayoutConstraint activateConstraints:@[
        [header.heightAnchor constraintEqualToConstant:30],
        [self.toolbarStack.centerXAnchor constraintEqualToAnchor:header.centerXAnchor],
        [self.toolbarStack.centerYAnchor constraintEqualToAnchor:header.centerYAnchor],
        [self.toolbarStack.leadingAnchor constraintGreaterThanOrEqualToAnchor:header.leadingAnchor],
        [self.toolbarStack.trailingAnchor constraintLessThanOrEqualToAnchor:header.trailingAnchor],
    ]];
    [rootStack addArrangedSubview:header];
    [self addSpacerToStack:rootStack height:8];

    NSScrollView *scroll = [[NSScrollView alloc] init];
    scroll.drawsBackground = NO;
    scroll.hasVerticalScroller = YES;
    scroll.autohidesScrollers = YES;
    scroll.translatesAutoresizingMaskIntoConstraints = NO;

    self.contentStack = [[CPFlippedStackView alloc] init];
    self.contentStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    self.contentStack.alignment = NSLayoutAttributeWidth;
    self.contentStack.spacing = 8;
    self.contentStack.edgeInsets = NSEdgeInsetsMake(0, 0, 0, 0);
    self.contentStack.translatesAutoresizingMaskIntoConstraints = NO;
    scroll.documentView = self.contentStack;
    [self.contentStack.widthAnchor constraintEqualToAnchor:scroll.contentView.widthAnchor].active = YES;

    [rootStack addArrangedSubview:scroll];
    [scroll.heightAnchor constraintGreaterThanOrEqualToConstant:300].active = YES;

    [self renderActiveSection];
}

- (void)renderActiveSection {
    NSArray *oldViews = self.contentStack.arrangedSubviews.copy;
    for (NSView *view in oldViews) {
        [self.contentStack removeArrangedSubview:view];
        [view removeFromSuperview];
    }
    self.accountTable = nil;
    self.inspectorStack = nil;

    if ([self.activeSection isEqualToString:@"accounts"]) {
        [self renderAccountsSection];
    } else if ([self.activeSection isEqualToString:@"config"]) {
        [self renderConfigSection];
    } else if ([self.activeSection isEqualToString:@"logs"]) {
        [self renderLogsSection];
    } else {
        [self renderOverviewSection];
    }
    [self reloadAccountTableSelection];
    [self updateHeaderText];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.window.contentView layoutSubtreeIfNeeded];
        [self auditVisibleButtonsWithContext:self.activeSection ?: @"unknown"];
    });
}

- (void)renderOverviewSection {
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self totalQuotaCard] width:450]];
    if ([self shouldShowTokenHistoryWarning]) {
        [self.contentStack addArrangedSubview:[self constrainedContentView:[self tokenHistoryWarningCard] width:450]];
    }
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self tokenStatsCard] width:450]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self tokenBarChartCard] width:450]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self tokenHeatmapCard] width:450]];
}

- (void)renderDashboardSection {
    if ([self shouldShowSetupCard]) {
        [self.contentStack addArrangedSubview:[self constrainedContentView:[self setupChecklistCard]]];
    }
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self metricsRow]]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self accountsTableCardWithHeight:176]]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self inspectorCardWithHeight:126 compact:YES]]];
}

- (void)renderAccountsSection {
    if ([self shouldShowSetupCard]) {
        [self.contentStack addArrangedSubview:[self constrainedContentView:[self setupChecklistCard]]];
    }
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self accountManagementCard]]];
}

- (void)renderQuotaSection {
    [self.contentStack addArrangedSubview:[self metricsRow]];
    [self.contentStack addArrangedSubview:[self quotaCard]];
}

- (void)renderConfigSection {
    if ([self shouldShowSetupCard]) {
        [self.contentStack addArrangedSubview:[self constrainedContentView:[self setupChecklistCard] width:450]];
    }
    if ([self hasRuntimeManifestMismatch] || [self hasVersionMismatch] || [self hasUsageStorageMismatch]) {
        [self.contentStack addArrangedSubview:[self constrainedContentView:[self runtimeSyncCard] width:450]];
    }
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self proxyConfirmationCard] width:450]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self configCardsRow]]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self strategyCard]]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self updateDiagnosticsCard]]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self pathsCard]]];
}

- (void)renderLogsSection {
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self recentRequestsCard] width:450]];
}

- (NSView *)dashboardBottomRow {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeTop;
    row.spacing = 10;
    row.translatesAutoresizingMaskIntoConstraints = NO;
    NSView *inspector = [self inspectorCardWithHeight:112 compact:YES];
    NSView *log = [self logCardWithHeight:112];
    [row addArrangedSubview:inspector];
    [row addArrangedSubview:log];
    [inspector.widthAnchor constraintEqualToAnchor:log.widthAnchor multiplier:1.05].active = YES;
    return row;
}

- (BOOL)shouldShowSetupCard {
    if (!self.statusSnapshot.count) {
        return YES;
    }
    if (!CPBool(self.statusSnapshot[@"resource_runtime_exists"])) {
        return YES;
    }
    if (!CPBool(self.statusSnapshot[@"runtime_exists"])) {
        return YES;
    }
    if (!CPBool(self.statusSnapshot[@"codex_cli_found"])) {
        return YES;
    }
    if (!CPBool(self.statusSnapshot[@"installed"]) || !CPBool(self.statusSnapshot[@"loaded"])) {
        return YES;
    }
    if (!CPBool(self.statusSnapshot[@"enabled"])) {
        return YES;
    }
    if (CPDouble(self.statusSnapshot[@"active_accounts"]) <= 0) {
        return YES;
    }
    return ![self proxyTrafficConfirmed];
}

- (NSDictionary *)runtimeManifestSnapshot {
    return CPDict(self.statusSnapshot[@"manifest"]);
}

- (BOOL)hasRuntimeManifestMismatch {
    if (!self.statusSnapshot.count) {
        return NO;
    }
    if (self.statusSnapshot[@"manifest_ok"] && !CPBool(self.statusSnapshot[@"manifest_ok"])) {
        return YES;
    }
    NSDictionary *manifest = [self runtimeManifestSnapshot];
    return manifest.count > 0 && manifest[@"ok"] && !CPBool(manifest[@"ok"]);
}

- (BOOL)hasUsageStorageMismatch {
    NSDictionary *usage = CPDict(self.statusSnapshot[@"usage"]);
    if (!usage.count) {
        return NO;
    }
    if (usage[@"observed_columns_ok"] && !CPBool(usage[@"observed_columns_ok"])) {
        return YES;
    }
    return NO;
}

- (NSString *)runtimeManifestFilesSummary {
    NSDictionary *manifest = [self runtimeManifestSnapshot];
    NSMutableArray<NSString *> *parts = [NSMutableArray array];
    NSDictionary<NSString *, NSString *> *titles = @{
        @"changed": @"变更文件",
        @"missing": @"缺失文件",
        @"extra": @"多余文件",
        @"expected_missing": @"内置缺失",
        @"observed_missing": @"运行缺失",
    };
    for (NSString *key in @[@"changed", @"missing", @"extra", @"expected_missing", @"observed_missing"]) {
        NSArray *items = CPArray(manifest[key]);
        if (items.count == 0) {
            continue;
        }
        NSMutableArray<NSString *> *names = [NSMutableArray array];
        for (id item in items) {
            NSString *name = CPString(item);
            if (name.length) {
                [names addObject:name];
            }
        }
        if (names.count) {
            [parts addObject:[NSString stringWithFormat:@"%@：%@", titles[key], [names componentsJoinedByString:@", "]]];
        }
    }
    return [parts componentsJoinedByString:@"；"];
}

- (BOOL)hasVersionMismatch {
    if (!self.statusSnapshot.count) {
        return NO;
    }
    NSString *frontend = CPString(self.frontendVersion);
    NSString *bundle = CPString(self.statusSnapshot[@"bundle_version"]);
    NSString *runtime = CPString(self.statusSnapshot[@"runtime_version"]);
    NSString *proxyVersion = CPString(self.statusSnapshot[@"proxy_version"]);
    if (!proxyVersion.length) {
        proxyVersion = CPString(self.statusSnapshot[@"version"]);
    }
    BOOL knownMismatch = NO;
    if (frontend.length && bundle.length && ![frontend isEqualToString:bundle]) {
        knownMismatch = YES;
    }
    if (bundle.length && runtime.length && ![bundle isEqualToString:runtime]) {
        knownMismatch = YES;
    }
    if (bundle.length && proxyVersion.length && ![bundle isEqualToString:proxyVersion]) {
        knownMismatch = YES;
    }
    return knownMismatch || CPBool(self.statusSnapshot[@"version_mismatch"]);
}

- (BOOL)shouldShowTokenHistoryWarning {
    if (!CPBool(self.statusSnapshot[@"running"])) {
        return NO;
    }
    if (!self.statusSnapshot[@"token_usage_events_available"]) {
        return NO;
    }
    return !CPBool(self.statusSnapshot[@"token_usage_events_available"]);
}

- (NSView *)tokenHistoryWarningCard {
    NSView *card = [self cardViewWithBackground:[[NSColor systemOrangeColor] colorWithAlphaComponent:0.10]];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 6;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(10, 12, 10, 12)];
    [stack addArrangedSubview:[self labelWithText:@"后台未同步" font:[NSFont systemFontOfSize:14 weight:NSFontWeightBold] color:NSColor.systemOrangeColor]];
    [stack addArrangedSubview:[self emptyStateLabel:@"Token 历史事件接口不可用，历史列表和图表可能不完整。请使用主窗口顶部的“启动/修复”，或在配置页执行“应用更新”。"]];
    return card;
}

- (NSView *)runtimeSyncCard {
    BOOL versionMismatch = [self hasVersionMismatch];
    BOOL manifestMismatch = [self hasRuntimeManifestMismatch] && !versionMismatch;
    BOOL usageMismatch = [self hasUsageStorageMismatch] && !versionMismatch && !manifestMismatch;
    NSView *card = [self cardViewWithBackground:[[NSColor systemOrangeColor] colorWithAlphaComponent:0.12]];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];
    NSString *title = usageMismatch ? @"Token 统计未迁移" : (manifestMismatch ? @"运行文件未同步" : @"版本不同步");
    [stack addArrangedSubview:[self labelWithText:title
                                             font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold]
                                            color:NSColor.systemOrangeColor]];
    NSString *message = @"后台或运行目录版本与当前 App 不一致。请退出并重新打开小腊肠，或使用主窗口顶部的“启动/修复”同步后台。";
    if (manifestMismatch) {
        message = @"运行目录中的文件与当前 App 内置文件不一致。使用主窗口顶部的“启动/修复”后，小腊肠会更新后台运行文件并重启代理。";
    } else if (usageMismatch) {
        message = @"Token 统计库还没有完成缓存/推理捕获状态迁移。使用主窗口顶部的“启动/修复”会重启后台并触发迁移。";
    }
    [stack addArrangedSubview:[self emptyStateLabel:message]];
    NSString *fileSummary = [self runtimeManifestFilesSummary];
    if (manifestMismatch && fileSummary.length) {
        [stack addArrangedSubview:[self emptyStateLabel:fileSummary]];
    }
    [stack addArrangedSubview:[self versionDiagnosticsGridCompact:YES]];
    return card;
}

- (BOOL)serviceReady {
    return CPBool(self.statusSnapshot[@"installed"]) && CPBool(self.statusSnapshot[@"loaded"])
        && !CPBool(self.statusSnapshot[@"needs_repair"])
        && !CPBool(self.statusSnapshot[@"version_mismatch"])
        && !CPBool(self.statusSnapshot[@"migration_required"]);
}

- (BOOL)hasUsableAccount {
    return CPDouble(self.statusSnapshot[@"active_accounts"]) > 0;
}

- (BOOL)hasAnyAccount {
    return CPDouble(self.statusSnapshot[@"total_accounts"]) > 0 || self.accounts.count > 0;
}

- (BOOL)isModelProxyPath:(NSString *)path {
    return [path hasPrefix:@"/v1/responses"]
        || [path hasPrefix:@"/backend-api/codex/responses"];
}

- (BOOL)isBackgroundOnlyPath:(NSString *)path {
    return [path hasPrefix:@"/v1/models"]
        || [path hasPrefix:@"/backend-api/wham/"]
        || [path hasPrefix:@"/backend-api/connectors/"]
        || [path hasPrefix:@"/backend-api/plugins/"]
        || [path hasPrefix:@"/backend-api/codex/analytics-events"]
        || [path hasPrefix:@"/backend-api/codex/usage"];
}

- (BOOL)proxyTrafficConfirmed {
    NSDictionary *modelProxy = CPDict(self.statusSnapshot[@"model_proxy"]);
    if (CPBool(modelProxy[@"observed"])) {
        return YES;
    }
    for (NSDictionary *row in CPArray(self.statusSnapshot[@"recent_requests"])) {
        NSString *account = CPString(row[@"account"]);
        NSString *path = CPString(row[@"path"]);
        if (![account isEqualToString:@"local"] && [self isModelProxyPath:path]) {
            return YES;
        }
    }
    return NO;
}

- (BOOL)hasOnlyBackgroundTraffic {
    BOOL sawBackground = NO;
    for (NSDictionary *row in CPArray(self.statusSnapshot[@"recent_requests"])) {
        NSString *path = CPString(row[@"path"]);
        if ([self isModelProxyPath:path]) {
            return NO;
        }
        if ([self isBackgroundOnlyPath:path]) {
            sawBackground = YES;
        }
    }
    return sawBackground;
}

- (NSString *)proxyConfirmationTitle {
    if ([self proxyTrafficConfirmed]) {
        return @"已确认走代理";
    }
    if (!CPBool(self.statusSnapshot[@"running"])) {
        return @"代理未确认";
    }
    if (!CPBool(self.statusSnapshot[@"enabled"])) {
        return @"Codex 仍是直连";
    }
    if (![self hasUsableAccount]) {
        return @"等待可用账号";
    }
    if ([self hasOnlyBackgroundTraffic]) {
        return @"等待真实对话";
    }
    return @"等待确认";
}

- (NSString *)proxyConfirmationDetail {
    NSDictionary *modelProxy = CPDict(self.statusSnapshot[@"model_proxy"]);
    if ([self proxyTrafficConfirmed]) {
        NSArray *recent = CPArray(modelProxy[@"recent_model_requests"]);
        NSDictionary *row = recent.count ? CPDict(recent.firstObject) : CPDict(CPArray(self.statusSnapshot[@"recent_requests"]).firstObject);
        NSString *account = CPDisplayString(row[@"account"]);
        NSString *path = CPDisplayString(row[@"path"]);
        return [NSString stringWithFormat:@"最近模型请求已由账号 %@ 处理：%@", account, path];
    }
    if (!CPBool(self.statusSnapshot[@"running"])) {
        return @"点击“启动/修复/更新后台”，让本机代理先在线。";
    }
    if (!CPBool(self.statusSnapshot[@"enabled"])) {
        return @"点击“启用代理”，让 Codex 使用本机账号池。";
    }
    if (![self hasUsableAccount]) {
        return @"请添加、导入或修复账号，至少需要 1 个可用账号。";
    }
    if ([self hasOnlyBackgroundTraffic]) {
        return @"已看到 Codex 后台请求。请在 Codex 发起一次真实对话来完成确认。";
    }
    return @"打开 Codex 后发起一次真实对话；看到模型请求经过账号池后会自动确认。";
}

- (NSColor *)proxyConfirmationColor {
    if ([self proxyTrafficConfirmed]) {
        return NSColor.systemGreenColor;
    }
    if (!CPBool(self.statusSnapshot[@"running"]) || !CPBool(self.statusSnapshot[@"enabled"]) || ![self hasUsableAccount]) {
        return NSColor.systemOrangeColor;
    }
    return NSColor.controlAccentColor;
}

- (NSView *)proxyConfirmationCard {
    NSView *card = [self cardViewWithBackground:NSColor.textBackgroundColor];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    header.spacing = 8;
    [header addArrangedSubview:[self statusDotWithColor:[self proxyConfirmationColor]]];
    [header addArrangedSubview:[self labelWithText:@"代理确认" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [header addArrangedSubview:[self labelWithText:[self proxyConfirmationTitle] font:[NSFont systemFontOfSize:13 weight:NSFontWeightSemibold] color:[self proxyConfirmationColor]]];
    [stack addArrangedSubview:header];
    [stack addArrangedSubview:[self emptyStateLabel:[self proxyConfirmationDetail]]];
    return card;
}

- (NSDictionary *)selectionSnapshot {
    return CPDict(self.statusSnapshot[@"selection"]);
}

- (NSString *)selectionExplanationText {
    NSDictionary *selection = [self selectionSnapshot];
    NSString *predicted = CPString(selection[@"predicted_account"]);
    if (!selection.count) {
        return @"额度优先正在等待代理在线后读取账号选择解释。";
    }
    if (!predicted.length) {
        return @"额度优先暂时没有可用账号。请检查账号是否禁用、冷却、缺少令牌或认证异常。";
    }
    NSString *note = CPString(selection[@"note"]);
    if ([note containsString:@"quota data is incomplete"]) {
        return [NSString stringWithFormat:@"额度数据未完整刷新，当前会先使用账号 %@；额度恢复后继续按额度优先。", predicted];
    }
    return [NSString stringWithFormat:@"额度优先当前会使用账号 %@。系统会优先选择额度压力较低的账号。", predicted];
}

- (NSString *)selectionReasonForAccountName:(NSString *)name {
    if (!name.length) {
        return @"-";
    }
    NSDictionary *selection = [self selectionSnapshot];
    NSString *predicted = CPString(selection[@"predicted_account"]);
    if ([predicted isEqualToString:name]) {
        NSString *note = CPString(selection[@"note"]);
        if ([note containsString:@"quota data is incomplete"]) {
            return @"当前候选；额度数据不完整时自动容错";
        }
        return @"当前候选；额度压力较低";
    }
    for (NSDictionary *row in CPArray(selection[@"accounts"])) {
        if (![CPString(row[@"name"]) isEqualToString:name]) {
            continue;
        }
        NSArray *reasons = CPArray(row[@"reasons"]);
        if (!reasons.count) {
            return @"可参与额度优先";
        }
        NSMutableArray<NSString *> *labels = [NSMutableArray array];
        for (id reasonValue in reasons) {
            NSString *reason = CPString(reasonValue);
            if ([reason isEqualToString:@"disabled"]) {
                [labels addObject:@"已禁用"];
            } else if ([reason hasPrefix:@"rate_limit"] || [reason containsString:@"cooldown"]) {
                [labels addObject:@"冷却中"];
            } else if ([reason isEqualToString:@"missing_token"]) {
                [labels addObject:@"缺少令牌"];
            } else if ([reason isEqualToString:@"missing_quota"]) {
                [labels addObject:@"额度待刷新"];
            } else if (reason.length) {
                [labels addObject:reason];
            }
        }
        return labels.count ? [labels componentsJoinedByString:@"、"] : @"可参与额度优先";
    }
    return @"等待代理在线后解释";
}

- (NSView *)selectionExplanationCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];
    [stack addArrangedSubview:[self labelWithText:@"额度优先" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    [stack addArrangedSubview:[self emptyStateLabel:[self selectionExplanationText]]];
    return card;
}

- (NSView *)setupChecklistCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintGreaterThanOrEqualToConstant:166].active = YES;

    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    header.spacing = 8;
    [header addArrangedSubview:[self labelWithText:@"首次设置" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [header addArrangedSubview:[self actionButtonWithTitle:[self setupPrimaryActionTitle] symbol:[self setupPrimaryActionSymbol] selector:@selector(continueSetupAction:) primary:YES]];
    [stack addArrangedSubview:header];

    BOOL runtimeReady = CPBool(self.statusSnapshot[@"runtime_exists"]) && CPBool(self.statusSnapshot[@"resource_runtime_exists"]);
    BOOL cliReady = CPBool(self.statusSnapshot[@"codex_cli_found"]);
    BOOL serviceReady = [self serviceReady];
    BOOL accountReady = [self hasUsableAccount];
    BOOL proxyReady = CPBool(self.statusSnapshot[@"enabled"]);
    BOOL confirmed = [self proxyTrafficConfirmed];
    NSString *cliDetail = cliReady
        ? CPDisplayString(self.statusSnapshot[@"codex_cli"])
        : CPDisplayString(self.statusSnapshot[@"codex_cli_error"]);
    NSString *serviceDetail = serviceReady ? @"后台服务已运行" : @"点击“启动/修复/更新后台”安装、修复或更新";
    NSString *accountDetail = accountReady
        ? @"至少 1 个账号可用"
        : ([self hasAnyAccount] ? @"已有账号需要启用、刷新令牌或解除冷却" : @"添加或导入账号后才能进入账号池");
    NSString *proxyDetail = proxyReady ? @"Codex 已配置为代理模式" : @"点击“启用代理”写入 Codex 配置";
    NSString *openDetail = confirmed ? @"最近模型请求已确认走账号池" : @"打开 Codex 后发起一次真实对话";

    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"启动后台" detail:runtimeReady ? serviceDetail : @"正在准备或缺少 App 内置资源" ok:runtimeReady && serviceReady]];
    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"检测 Codex" detail:cliDetail ok:cliReady]];
    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"准备账号" detail:accountDetail ok:accountReady]];
    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"启用代理" detail:proxyDetail ok:proxyReady]];
    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"确认走代理" detail:openDetail ok:confirmed]];
    return card;
}

- (NSString *)setupPrimaryActionTitle {
    if (![self serviceReady]) {
        return @"启动/修复";
    }
    if (!CPBool(self.statusSnapshot[@"codex_cli_found"])) {
        return @"重新检测";
    }
    if (![self hasUsableAccount]) {
        return [self hasAnyAccount] ? @"修复账号" : @"添加账号";
    }
    if (!CPBool(self.statusSnapshot[@"enabled"])) {
        return @"启用代理";
    }
    if (![self proxyTrafficConfirmed]) {
        return @"打开 Codex";
    }
    return @"刷新状态";
}

- (NSString *)setupPrimaryActionSymbol {
    if (![self serviceReady]) {
        return @"play.circle.fill";
    }
    if (!CPBool(self.statusSnapshot[@"codex_cli_found"])) {
        return @"arrow.clockwise";
    }
    if (![self hasUsableAccount]) {
        return [self hasAnyAccount] ? @"exclamationmark.triangle" : @"person.crop.circle.badge.plus";
    }
    if (!CPBool(self.statusSnapshot[@"enabled"])) {
        return @"checkmark.shield";
    }
    if (![self proxyTrafficConfirmed]) {
        return @"arrow.up.forward.app";
    }
    return @"arrow.clockwise";
}

- (NSView *)setupStatusLineWithTitle:(NSString *)title detail:(NSString *)detail ok:(BOOL)ok {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.spacing = 8;
    [row addArrangedSubview:[self statusDotWithColor:ok ? NSColor.systemGreenColor : NSColor.systemOrangeColor]];
    NSTextField *titleLabel = [self labelWithText:title font:[NSFont systemFontOfSize:12 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor];
    [titleLabel.widthAnchor constraintEqualToConstant:62].active = YES;
    NSTextField *detailLabel = [self labelWithText:detail font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular] color:ok ? NSColor.labelColor : NSColor.systemOrangeColor];
    detailLabel.lineBreakMode = NSLineBreakByTruncatingMiddle;
    [row addArrangedSubview:titleLabel];
    [row addArrangedSubview:detailLabel];
    return row;
}

- (NSView *)metricsRow {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.spacing = 10;
    row.distribution = NSStackViewDistributionFillEqually;
    row.translatesAutoresizingMaskIntoConstraints = NO;
    [row.heightAnchor constraintEqualToConstant:58].active = YES;

    NSString *running = CPBool(self.statusSnapshot[@"running"]) ? @"在线" : @"离线";
    NSColor *runningColor = CPBool(self.statusSnapshot[@"running"]) ? NSColor.systemGreenColor : NSColor.systemRedColor;
    NSString *accounts = [NSString stringWithFormat:@"%@ / %@",
                          CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                          CPDisplayString(self.statusSnapshot[@"total_accounts"])];
    NSString *strategy = CPDisplayString(self.statusSnapshot[@"strategy"]);
    if ([strategy isEqualToString:@"-"]) {
        strategy = CPBool(self.statusSnapshot[@"running"]) ? @"额度优先" : @"-";
    }
    strategy = [self strategyTitleForValue:strategy];
    NSString *port = CPDisplayString(CPDict(self.statusSnapshot[@"config"])[@"port"]);
    if ([port isEqualToString:@"-"]) {
        port = CPDisplayString(self.statusSnapshot[@"port"]);
    }
    if ([port isEqualToString:@"-"]) {
        port = @"8800";
    }
    NSString *version = self.frontendVersion.length ? self.frontendVersion : CPDisplayString(self.statusSnapshot[@"version"]);
    NSArray<NSView *> *cards = @[
        [self metricCardWithTitle:@"代理状态" value:running detail:[NSString stringWithFormat:@"127.0.0.1:%@", port] color:runningColor],
        [self metricCardWithTitle:@"可用账号" value:accounts detail:@"active / total" color:NSColor.systemBlueColor],
        [self metricCardWithTitle:@"选择策略" value:strategy detail:@"自动容错" color:NSColor.systemPurpleColor],
        [self metricCardWithTitle:@"版本" value:CPDisplayString(version) detail:@"control center" color:NSColor.labelColor],
    ];
    for (NSView *card in cards) {
        [row addArrangedSubview:card];
        [card.widthAnchor constraintEqualToAnchor:row.widthAnchor multiplier:0.25 constant:-8].active = YES;
    }
    return row;
}

- (NSArray<NSDictionary *> *)tokenUsageRows {
    return CPArray(self.tokenUsageSnapshot[@"daily"]);
}

- (NSArray<NSDictionary *> *)tokenUsageWeeklyRows {
    NSArray *daily = [self tokenUsageRows];
    NSArray<NSString *> *keys = @[
        @"input_tokens",
        @"output_tokens",
        @"reasoning_tokens",
        @"cached_tokens",
        @"cache_tokens",
        @"cache_read_tokens",
        @"cache_creation_tokens",
        @"total_tokens",
        @"requests",
        @"unknown_requests",
    ];
    NSInteger leading = daily.count ? CPWeekdayIndexForDateString(CPString(daily.firstObject[@"date"])) : 0;
    NSMutableDictionary<NSNumber *, NSMutableDictionary *> *totalsByColumn = [NSMutableDictionary dictionary];
    for (NSInteger i = 0; i < daily.count; i++) {
        NSDictionary *day = daily[i];
        NSInteger column = (leading + i) / 7;
        NSNumber *columnKey = @(column);
        NSMutableDictionary *total = totalsByColumn[columnKey];
        if (!total) {
            total = [NSMutableDictionary dictionary];
            for (NSString *key in keys) {
                total[key] = @0;
            }
            NSString *date = CPString(day[@"date"]);
            total[@"week_start"] = date;
            totalsByColumn[columnKey] = total;
        }
        NSString *date = CPString(day[@"date"]);
        if (date.length) {
            total[@"week_end"] = date;
        }
        if (CPDouble(day[@"requests"]) > 0 || CPDouble(day[@"total_tokens"]) > 0) {
            total[@"active_days"] = @(CPDouble(total[@"active_days"]) + 1);
        }
        for (NSString *key in keys) {
            total[key] = @(CPDouble(total[key]) + CPDouble(day[key]));
        }
    }
    NSMutableArray<NSDictionary *> *rows = [NSMutableArray arrayWithCapacity:daily.count];
    for (NSInteger i = 0; i < daily.count; i++) {
        NSDictionary *day = daily[i];
        NSMutableDictionary *next = [day mutableCopy];
        NSInteger column = (leading + i) / 7;
        NSDictionary *week = totalsByColumn[@(column)];
        for (NSString *key in keys) {
            next[key] = @(CPDouble(week[key]));
        }
        next[@"active_days"] = @(CPDouble(week[@"active_days"]));
        next[@"heat_value"] = next[@"active_days"];
        next[@"heat_max"] = @7;
        NSString *weekStart = CPString(week[@"week_start"]);
        NSString *weekEnd = CPString(week[@"week_end"]);
        if (weekStart.length) {
            next[@"week_start"] = weekStart;
            next[@"period_label"] = weekEnd.length && ![weekEnd isEqualToString:weekStart]
                ? [NSString stringWithFormat:@"%@ 至 %@", weekStart, weekEnd]
                : weekStart;
        }
        [rows addObject:next];
    }
    return rows;
}

- (NSArray<NSDictionary *> *)tokenUsageBarRows {
    NSArray *daily = [self tokenUsageRows];
    if (daily.count <= 31) {
        return daily;
    }
    return [daily subarrayWithRange:NSMakeRange(daily.count - 31, 31)];
}

- (NSArray<NSDictionary *> *)tokenUsageCumulativeRows {
    NSArray *daily = [self tokenUsageRows];
    NSMutableArray<NSDictionary *> *rows = [NSMutableArray arrayWithCapacity:daily.count];
    NSArray<NSString *> *keys = @[
        @"input_tokens",
        @"output_tokens",
        @"reasoning_tokens",
        @"cached_tokens",
        @"cache_tokens",
        @"cache_read_tokens",
        @"cache_creation_tokens",
        @"total_tokens",
        @"requests",
        @"unknown_requests",
    ];
    NSMutableDictionary *running = [NSMutableDictionary dictionary];
    for (NSString *key in keys) {
        running[key] = @0;
    }
    for (NSDictionary *row in daily) {
        NSMutableDictionary *next = [row mutableCopy];
        NSString *date = CPString(row[@"date"]);
        for (NSString *key in keys) {
            double value = CPDouble(running[key]) + CPDouble(row[key]);
            running[key] = @(value);
            next[key] = @(value);
        }
        if (date.length) {
            next[@"period_label"] = [NSString stringWithFormat:@"截至 %@", date];
        }
        [rows addObject:next];
    }
    return rows;
}

- (NSArray<NSDictionary *> *)tokenUsageHeatmapRows {
    if (self.tokenUsageMode == 1) {
        return [self tokenUsageWeeklyRows];
    }
    if (self.tokenUsageMode == 2) {
        return [self tokenUsageCumulativeRows];
    }
    return [self tokenUsageRows];
}

- (NSDictionary *)tokenUsageTotal {
    return CPDict(self.tokenUsageSnapshot[@"total"]);
}

- (NSArray<NSDictionary *> *)tokenUsageEventRows {
    return CPArray(self.tokenUsageEvents);
}

- (NSString *)formatTokenCount:(double)value {
    if (value >= 1000000) {
        return [NSString stringWithFormat:@"%.1fM", value / 1000000.0];
    }
    if (value >= 1000) {
        return [NSString stringWithFormat:@"%.1fK", value / 1000.0];
    }
    return [NSString stringWithFormat:@"%.0f", value];
}

- (NSDictionary *)quotaSummary {
    NSInteger quotaAccounts = 0;
    NSInteger unknownQuota = 0;
    NSTimeInterval latestFetched = 0;
    double remain5h = 0;
    double remain7d = 0;
    for (NSDictionary *account in self.accounts) {
        if (!CPBool(account[@"enabled"]) || !CPBool(account[@"has_tokens"])) {
            continue;
        }
        quotaAccounts += 1;
        NSString *name = CPString(account[@"name"]);
        NSDictionary *quota = CPDict(self.quotaSnapshot[name]);
        if (!quota.count || quota[@"error"]) {
            unknownQuota += 1;
        } else {
            latestFetched = MAX(latestFetched, CPDouble(quota[@"_fetched_at"]));
        }
        remain5h += [self quotaRemainingForAccountName:name weekly:NO];
        remain7d += [self quotaRemainingForAccountName:name weekly:YES];
    }
    double capacity = quotaAccounts * 100.0;
    return @{
        @"accounts": @(quotaAccounts),
        @"unknown": @(unknownQuota),
        @"latestFetched": @(latestFetched),
        @"remain5h": @(remain5h),
        @"remain7d": @(remain7d),
        @"capacity": @(capacity),
    };
}

- (NSString *)quotaTotalTextForWeekly:(BOOL)weekly {
    NSDictionary *summary = [self quotaSummary];
    NSInteger quotaAccounts = (NSInteger)CPDouble(summary[@"accounts"]);
    NSInteger unknownQuota = (NSInteger)CPDouble(summary[@"unknown"]);
    double capacity = CPDouble(summary[@"capacity"]);
    if (quotaAccounts <= 0 || capacity <= 0 || unknownQuota >= quotaAccounts) {
        return @"额度待刷新";
    }
    double remaining = CPDouble(summary[weekly ? @"remain7d" : @"remain5h"]);
    return [NSString stringWithFormat:@"%.0f%% / %.0f%%", remaining, capacity];
}

- (NSView *)totalQuotaCard {
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeLeading;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [stack.heightAnchor constraintGreaterThanOrEqualToConstant:92].active = YES;

    NSDictionary *summary = [self quotaSummary];
    NSInteger quotaAccounts = (NSInteger)CPDouble(summary[@"accounts"]);
    NSInteger unknownQuota = (NSInteger)CPDouble(summary[@"unknown"]);
    NSTimeInterval latestFetched = CPDouble(summary[@"latestFetched"]);
    double remain5h = CPDouble(summary[@"remain5h"]);
    double remain7d = CPDouble(summary[@"remain7d"]);
    double capacity = CPDouble(summary[@"capacity"]);
    double remain5hRatio = capacity > 0 ? remain5h / capacity : 0;
    double remain7dRatio = capacity > 0 ? remain7d / capacity : 0;

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeFirstBaseline;
    header.spacing = 10;
    NSTextField *title = [self labelWithText:@"账号额度" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor];
    [title setContentCompressionResistancePriority:NSLayoutPriorityRequired forOrientation:NSLayoutConstraintOrientationHorizontal];
    [header addArrangedSubview:title];
    NSString *accountText = quotaAccounts > 0 ? [NSString stringWithFormat:@"%@ 个可用账号", @(quotaAccounts)] : @"暂无可用账号";
    if (unknownQuota > 0) {
        accountText = [accountText stringByAppendingFormat:@" · %ld 个额度等待刷新", (long)unknownQuota];
    }
    NSTextField *accountLabel = [self labelWithText:accountText
                                               font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular]
                                              color:unknownQuota > 0 ? NSColor.systemOrangeColor : NSColor.secondaryLabelColor];
    accountLabel.maximumNumberOfLines = 1;
    accountLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    [header addArrangedSubview:accountLabel];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    NSString *refreshText = latestFetched > 0 ? [NSString stringWithFormat:@"刷新\n%@", CPFullDateTime(@(latestFetched))] : @"未刷新";
    NSTextField *refreshLabel = [self labelWithText:refreshText
                                               font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular]
                                              color:NSColor.secondaryLabelColor];
    refreshLabel.alignment = NSTextAlignmentRight;
    refreshLabel.maximumNumberOfLines = 2;
    refreshLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    [refreshLabel.widthAnchor constraintEqualToConstant:126].active = YES;
    [header addArrangedSubview:refreshLabel];
    [stack addArrangedSubview:header];

    [stack addArrangedSubview:[self quotaLaneWithTitle:@"5h 剩余"
                                           captionText:[self quotaTotalTextForWeekly:NO]
                                              progress:remain5hRatio
                                                 color:NSColor.controlAccentColor]];
    [stack addArrangedSubview:[self quotaLaneWithTitle:@"7d 剩余"
                                           captionText:[self quotaTotalTextForWeekly:YES]
                                              progress:remain7dRatio
                                                 color:NSColor.systemGreenColor]];
    return stack;
}

- (NSView *)quotaLaneWithTitle:(NSString *)title captionText:(NSString *)captionText progress:(double)progress color:(NSColor *)color {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.spacing = 8;
    row.translatesAutoresizingMaskIntoConstraints = NO;
    [row.heightAnchor constraintEqualToConstant:30].active = YES;

    NSTextField *titleLabel = [self labelWithText:title ?: @"额度"
                                             font:[NSFont systemFontOfSize:13 weight:NSFontWeightSemibold]
                                            color:NSColor.secondaryLabelColor];
    [titleLabel.widthAnchor constraintEqualToConstant:60].active = YES;
    [row addArrangedSubview:titleLabel];

    NSProgressIndicator *bar = [[NSProgressIndicator alloc] init];
    bar.indeterminate = NO;
    bar.minValue = 0;
    bar.maxValue = 100;
    bar.doubleValue = MAX(0, MIN(100, progress * 100.0));
    bar.controlSize = NSControlSizeSmall;
    bar.translatesAutoresizingMaskIntoConstraints = NO;
    [bar.widthAnchor constraintEqualToConstant:136].active = YES;
    [bar setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    [row addArrangedSubview:bar];

    NSTextField *caption = [self labelWithText:captionText ?: @"额度待刷新"
                                          font:[NSFont monospacedDigitSystemFontOfSize:13 weight:NSFontWeightSemibold]
                                         color:color ?: NSColor.labelColor];
    caption.alignment = NSTextAlignmentRight;
    caption.maximumNumberOfLines = 1;
    caption.lineBreakMode = NSLineBreakByTruncatingTail;
    [caption.widthAnchor constraintEqualToConstant:118].active = YES;
    [row addArrangedSubview:caption];
    return row;
}

- (NSView *)quotaRingWithTitle:(NSString *)title progress:(double)progress captionText:(NSString *)captionText color:(NSColor *)color {
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeCenterX;
    stack.spacing = 6;
    CPQuotaRingView *ring = [[CPQuotaRingView alloc] init];
    ring.translatesAutoresizingMaskIntoConstraints = NO;
    ring.progress = progress;
    ring.ringColor = color;
    ring.centerText = title ?: @"-";
    [ring.widthAnchor constraintEqualToConstant:92].active = YES;
    [ring.heightAnchor constraintEqualToConstant:92].active = YES;
    [stack addArrangedSubview:ring];
    NSTextField *caption = [self labelWithText:captionText ?: @"-"
                                          font:[NSFont monospacedDigitSystemFontOfSize:13 weight:NSFontWeightSemibold]
                                         color:color];
    caption.alignment = NSTextAlignmentCenter;
    [stack addArrangedSubview:caption];
    return stack;
}

- (NSView *)quotaSummaryLineWithTitle:(NSString *)title value:(double)value color:(NSColor *)color capacity:(double)capacity {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.spacing = 8;
    [row addArrangedSubview:[self labelWithText:title font:[NSFont systemFontOfSize:12 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor]];
    double percent = capacity > 0 ? (value / capacity) * 100.0 : 0;
    NSTextField *valueLabel = [self labelWithText:[NSString stringWithFormat:@"%.0f%%", percent] font:[NSFont systemFontOfSize:13 weight:NSFontWeightSemibold] color:color];
    [valueLabel.widthAnchor constraintEqualToConstant:42].active = YES;
    [row addArrangedSubview:valueLabel];
    NSProgressIndicator *progress = [self progressWithValue:percent];
    [row addArrangedSubview:progress];
    NSString *detail = capacity > 0
        ? [NSString stringWithFormat:@"%.0f%% / %.0f%%", value, capacity]
        : @"暂无容量";
    NSTextField *detailLabel = [self labelWithText:detail font:[NSFont systemFontOfSize:10 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
    [detailLabel.widthAnchor constraintEqualToConstant:78].active = YES;
    [row addArrangedSubview:detailLabel];
    return row;
}

- (NSView *)tokenStatsCard {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.spacing = 8;
    row.distribution = NSStackViewDistributionFillEqually;
    row.translatesAutoresizingMaskIntoConstraints = NO;
    NSDictionary *total = [self tokenUsageTotal];
    NSArray *daily = CPArray(self.tokenUsageSnapshot[@"daily"]);
    double todayTokens = daily.count ? CPDouble(daily.lastObject[@"total_tokens"]) : 0;
    double weeklyTokens = 0;
    NSArray *weekly = CPArray(self.tokenUsageSnapshot[@"weekly"]);
    if (weekly.count) {
        weeklyTokens = CPDouble(weekly.lastObject[@"total_tokens"]);
    }
    double knownRequests = MAX(0, CPDouble(total[@"requests"]) - CPDouble(total[@"unknown_requests"]));
    NSArray<NSView *> *cards = @[
        [self metricCardWithTitle:@"今日 Token" value:[self formatTokenCount:todayTokens] detail:@"" color:NSColor.controlAccentColor],
        [self metricCardWithTitle:@"本周 Token" value:[self formatTokenCount:weeklyTokens] detail:@"" color:NSColor.systemGreenColor],
        [self metricCardWithTitle:@"请求数" value:[NSString stringWithFormat:@"%.0f", knownRequests] detail:@"" color:NSColor.systemOrangeColor],
    ];
    for (NSView *card in cards) {
        [row addArrangedSubview:card];
        [card.widthAnchor constraintEqualToAnchor:row.widthAnchor multiplier:(1.0 / 3.0) constant:-6].active = YES;
    }
    return row;
}

- (NSView *)tokenBarChartCard {
    NSView *card = [self cardViewWithBackground:NSColor.textBackgroundColor];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintEqualToConstant:118].active = YES;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 4;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 2, 12)];

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    [header addArrangedSubview:[self labelWithText:@"最近 31 天柱状图" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [stack addArrangedSubview:header];

    CPBarChartView *chart = [[CPBarChartView alloc] init];
    chart.rows = [self tokenUsageBarRows];
    chart.translatesAutoresizingMaskIntoConstraints = NO;
    [chart.heightAnchor constraintEqualToConstant:78].active = YES;
    [stack addArrangedSubview:chart];
    return card;
}

- (NSView *)tokenHeatmapCard {
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeWidth;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [stack.heightAnchor constraintEqualToConstant:154].active = YES;

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    header.spacing = 4;
    [header addArrangedSubview:[self labelWithText:@"Token 活动" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    [header addArrangedSubview:[[NSView alloc] init]];
    [stack addArrangedSubview:header];

    NSStackView *body = [[NSStackView alloc] init];
    body.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    body.alignment = NSLayoutAttributeTop;
    body.spacing = 10;
    body.translatesAutoresizingMaskIntoConstraints = NO;

    NSStackView *modes = [[NSStackView alloc] init];
    modes.orientation = NSUserInterfaceLayoutOrientationVertical;
    modes.alignment = NSLayoutAttributeWidth;
    modes.spacing = 6;
    modes.translatesAutoresizingMaskIntoConstraints = NO;
    [modes.widthAnchor constraintEqualToConstant:58].active = YES;
    [modes addArrangedSubview:[self tokenHeatmapModeButtonWithTitle:@"每日" tag:0]];
    [modes addArrangedSubview:[self tokenHeatmapModeButtonWithTitle:@"每周" tag:1]];
    [modes addArrangedSubview:[self tokenHeatmapModeButtonWithTitle:@"累计" tag:2]];
    [body addArrangedSubview:modes];

    CPHeatmapView *heatmap = [[CPHeatmapView alloc] init];
    heatmap.rows = [self tokenUsageHeatmapRows];
    heatmap.cellMaxSize = 11;
    heatmap.cellMinSize = 5;
    heatmap.cellGap = 2;
    heatmap.monthLabelFontSize = 10;
    heatmap.translatesAutoresizingMaskIntoConstraints = NO;
    [heatmap.heightAnchor constraintEqualToConstant:104].active = YES;
    [body addArrangedSubview:heatmap];
    [heatmap.widthAnchor constraintEqualToAnchor:body.widthAnchor constant:-68].active = YES;
    [stack addArrangedSubview:body];
    return stack;
}

- (NSButton *)tokenHeatmapModeButtonWithTitle:(NSString *)title tag:(NSInteger)tag {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:@selector(tokenUsageModeAction:)];
    [button setButtonType:NSButtonTypeToggle];
    button.tag = tag;
    button.bezelStyle = NSBezelStyleRounded;
    button.controlSize = NSControlSizeSmall;
    button.font = [NSFont systemFontOfSize:12 weight:tag == self.tokenUsageMode ? NSFontWeightSemibold : NSFontWeightRegular];
    button.state = tag == self.tokenUsageMode ? NSControlStateValueOn : NSControlStateValueOff;
    button.translatesAutoresizingMaskIntoConstraints = NO;
    [button.heightAnchor constraintEqualToConstant:28].active = YES;
    return button;
}

- (NSView *)tokenEventHeaderRow {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.spacing = 8;
    NSArray *titles = @[@"时间", @"账号", @"模型", @"状态", @"Token"];
    NSArray *widths = @[@70, @72, @88, @42, @58];
    for (NSUInteger i = 0; i < titles.count; i++) {
        NSTextField *label = [self labelWithText:titles[i] font:[NSFont systemFontOfSize:10 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor];
        [label.widthAnchor constraintEqualToConstant:CPDouble(widths[i])].active = YES;
        [row addArrangedSubview:label];
    }
    return row;
}

- (NSView *)tokenEventRow:(NSDictionary *)event {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.spacing = 8;
    NSString *status = CPDisplayString(event[@"status"]);
    if ([status isEqualToString:@"-"] && CPBool(event[@"failed"])) {
        status = @"失败";
    }
    NSArray *values = @[
        CPRelativeTime(event[@"at"]),
        CPDisplayString(event[@"account"]),
        CPDisplayString(event[@"model"]),
        status,
        [self formatTokenCount:CPDouble(event[@"total_tokens"])],
    ];
    NSArray *widths = @[@70, @72, @88, @42, @58];
    for (NSUInteger i = 0; i < values.count; i++) {
        NSColor *color = i == 4 ? NSColor.controlAccentColor : NSColor.labelColor;
        if (i == 3 && ([status integerValue] >= 400 || [status isEqualToString:@"失败"])) {
            color = NSColor.systemOrangeColor;
        }
        NSTextField *label = [self labelWithText:values[i] font:[NSFont systemFontOfSize:11 weight:i == 4 ? NSFontWeightSemibold : NSFontWeightRegular] color:color];
        label.lineBreakMode = NSLineBreakByTruncatingMiddle;
        [label.widthAnchor constraintEqualToConstant:CPDouble(widths[i])].active = YES;
        [row addArrangedSubview:label];
    }
    return row;
}

- (NSString *)strategyTitleForValue:(NSString *)value {
    return @"额度优先";
}

- (NSString *)productModeTitle {
    NSString *mode = CPString(self.statusSnapshot[@"product_mode"]);
    if (!mode.length) {
        mode = CPString(CPDict(self.statusSnapshot[@"config"])[@"product_mode"]);
    }
    if ([mode isEqualToString:@"compatibility"]) {
        return @"兼容模式";
    }
    if ([mode isEqualToString:@"diagnostic"]) {
        return @"诊断模式";
    }
    return @"标准模式";
}

- (NSView *)accountAndInspectorRowWithCompact:(BOOL)compact {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeTop;
    row.spacing = 16;
    row.translatesAutoresizingMaskIntoConstraints = NO;

    NSView *accountsCard = [self accountsTableCardWithHeight:compact ? 300 : 410];
    [row addArrangedSubview:accountsCard];
    [accountsCard.widthAnchor constraintGreaterThanOrEqualToConstant:560].active = YES;

    NSView *inspector = [self inspectorCard];
    [row addArrangedSubview:inspector];
    [inspector.widthAnchor constraintEqualToConstant:300].active = YES;
    return row;
}

- (NSView *)accountsTableCardWithHeight:(CGFloat)height {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintEqualToConstant:height].active = YES;

    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    [header addArrangedSubview:[self labelWithText:@"账号列表" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [header addArrangedSubview:[self smallButtonWithTitle:@"扫描" symbol:@"arrow.triangle.2.circlepath" selector:@selector(scanAccountsAction:)]];
    [header addArrangedSubview:[self smallButtonWithTitle:@"登录" symbol:@"plus" selector:@selector(startLoginAction:)]];
    [header addArrangedSubview:[self smallButtonWithTitle:@"导入" symbol:@"square.and.arrow.down" selector:@selector(importCurrentAction:)]];
    [stack addArrangedSubview:header];

    NSScrollView *scroll = [[NSScrollView alloc] init];
    scroll.hasVerticalScroller = YES;
    scroll.hasHorizontalScroller = NO;
    scroll.autohidesScrollers = YES;
    scroll.drawsBackground = NO;
    scroll.translatesAutoresizingMaskIntoConstraints = NO;
    self.accountTable = [[NSTableView alloc] init];
    self.accountTable.delegate = self;
    self.accountTable.dataSource = self;
    self.accountTable.usesAlternatingRowBackgroundColors = NO;
    self.accountTable.allowsMultipleSelection = NO;
    self.accountTable.rowHeight = 28;
    self.accountTable.headerView = [[NSTableHeaderView alloc] initWithFrame:NSMakeRect(0, 0, 10, 24)];
    if (@available(macOS 11.0, *)) {
        self.accountTable.style = NSTableViewStyleFullWidth;
    }

    NSArray<NSDictionary *> *columns = @[
        @{@"id": @"name", @"title": @"名称", @"width": @40},
        @{@"id": @"email", @"title": @"邮箱", @"width": @158},
        @{@"id": @"state", @"title": @"状态", @"width": @40},
        @{@"id": @"quota", @"title": @"5h", @"width": @40},
        @{@"id": @"weekly", @"title": @"7d", @"width": @40},
    ];
    for (NSDictionary *spec in columns) {
        NSTableColumn *column = [[NSTableColumn alloc] initWithIdentifier:spec[@"id"]];
        column.title = spec[@"title"];
        column.width = [spec[@"width"] doubleValue];
        column.minWidth = 34;
        column.resizingMask = NSTableColumnNoResizing;
        BOOL leftAligned = [spec[@"id"] isEqualToString:@"name"] || [spec[@"id"] isEqualToString:@"email"];
        column.headerCell.alignment = leftAligned ? NSTextAlignmentLeft : NSTextAlignmentCenter;
        [self.accountTable addTableColumn:column];
    }
    self.accountTable.columnAutoresizingStyle = NSTableViewNoColumnAutoresizing;
    scroll.documentView = self.accountTable;
    [stack addArrangedSubview:scroll];
    [scroll.heightAnchor constraintGreaterThanOrEqualToConstant:height - 64].active = YES;
    return card;
}

- (NSView *)accountManagementCard {
    NSStackView *panes = [[NSStackView alloc] init];
    panes.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    panes.alignment = NSLayoutAttributeHeight;
    panes.spacing = 12;
    panes.translatesAutoresizingMaskIntoConstraints = NO;
    [panes.heightAnchor constraintEqualToConstant:300].active = YES;

    NSStackView *listPane = [[NSStackView alloc] init];
    listPane.orientation = NSUserInterfaceLayoutOrientationVertical;
    listPane.spacing = 10;
    listPane.translatesAutoresizingMaskIntoConstraints = NO;
    [panes addArrangedSubview:listPane];
    [listPane.widthAnchor constraintGreaterThanOrEqualToConstant:320].active = YES;

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    [header addArrangedSubview:[self labelWithText:@"账号管理" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [header addArrangedSubview:[self smallButtonWithTitle:@"扫描" symbol:@"arrow.triangle.2.circlepath" selector:@selector(scanAccountsAction:)]];
    [listPane addArrangedSubview:header];

    NSScrollView *scroll = [[NSScrollView alloc] init];
    scroll.hasVerticalScroller = YES;
    scroll.hasHorizontalScroller = NO;
    scroll.autohidesScrollers = YES;
    scroll.drawsBackground = NO;
    scroll.translatesAutoresizingMaskIntoConstraints = NO;
    self.accountTable = [[NSTableView alloc] init];
    self.accountTable.delegate = self;
    self.accountTable.dataSource = self;
    self.accountTable.usesAlternatingRowBackgroundColors = NO;
    self.accountTable.allowsMultipleSelection = NO;
    self.accountTable.rowHeight = 28;
    self.accountTable.headerView = [[NSTableHeaderView alloc] initWithFrame:NSMakeRect(0, 0, 10, 24)];
    if (@available(macOS 11.0, *)) {
        self.accountTable.style = NSTableViewStyleFullWidth;
    }

    NSArray<NSDictionary *> *columns = @[
        @{@"id": @"name", @"title": @"名称", @"width": @40},
        @{@"id": @"email", @"title": @"邮箱", @"width": @168},
        @{@"id": @"state", @"title": @"状态", @"width": @54},
        @{@"id": @"quota", @"title": @"5h", @"width": @48},
        @{@"id": @"weekly", @"title": @"7d", @"width": @48},
    ];
    for (NSDictionary *spec in columns) {
        NSTableColumn *column = [[NSTableColumn alloc] initWithIdentifier:spec[@"id"]];
        column.title = spec[@"title"];
        column.width = [spec[@"width"] doubleValue];
        column.minWidth = 34;
        column.resizingMask = NSTableColumnAutoresizingMask;
        BOOL leftAligned = [spec[@"id"] isEqualToString:@"name"] || [spec[@"id"] isEqualToString:@"email"];
        column.headerCell.alignment = leftAligned ? NSTextAlignmentLeft : NSTextAlignmentCenter;
        [self.accountTable addTableColumn:column];
    }
    self.accountTable.columnAutoresizingStyle = NSTableViewUniformColumnAutoresizingStyle;
    scroll.documentView = self.accountTable;
    [listPane addArrangedSubview:scroll];
    [scroll.heightAnchor constraintGreaterThanOrEqualToConstant:228].active = YES;
    [listPane.widthAnchor constraintEqualToAnchor:panes.widthAnchor multiplier:0.60 constant:-6].active = YES;

    CPThemedView *inspectorPanel = [[CPThemedView alloc] init];
    inspectorPanel.wantsLayer = YES;
    inspectorPanel.layer.cornerRadius = 0;
    inspectorPanel.layer.borderWidth = 0;
    inspectorPanel.cpBackgroundColor = NSColor.clearColor;
    inspectorPanel.cpBorderColor = NSColor.clearColor;
    inspectorPanel.translatesAutoresizingMaskIntoConstraints = NO;
    [panes addArrangedSubview:inspectorPanel];
    [inspectorPanel.widthAnchor constraintGreaterThanOrEqualToConstant:220].active = YES;

    self.compactInspector = YES;
    self.inspectorStack = [[NSStackView alloc] init];
    self.inspectorStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    self.inspectorStack.alignment = NSLayoutAttributeWidth;
    self.inspectorStack.spacing = 6;
    self.inspectorStack.translatesAutoresizingMaskIntoConstraints = NO;
    [inspectorPanel addSubview:self.inspectorStack];
    [self pinView:self.inspectorStack toView:inspectorPanel insets:NSEdgeInsetsMake(2, 10, 2, 0)];
    [self rebuildInspector];
    return panes;
}

- (NSView *)inspectorCard {
    return [self inspectorCardWithHeight:300 compact:NO];
}

- (NSView *)inspectorCardWithHeight:(CGFloat)height compact:(BOOL)compact {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    if (compact) {
        [card.heightAnchor constraintEqualToConstant:height].active = YES;
    } else {
        [card.heightAnchor constraintGreaterThanOrEqualToConstant:height].active = YES;
    }
    self.compactInspector = compact;
    self.inspectorStack = [[NSStackView alloc] init];
    self.inspectorStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    self.inspectorStack.alignment = NSLayoutAttributeWidth;
    self.inspectorStack.spacing = compact ? 7 : 12;
    self.inspectorStack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:self.inspectorStack];
    [self pinView:self.inspectorStack toView:card insets:compact ? NSEdgeInsetsMake(12, 12, 10, 12) : NSEdgeInsetsMake(18, 18, 18, 18)];
    [self rebuildInspector];
    return card;
}

- (NSView *)accountQuickActionsCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 12;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(16, 16, 16, 16)];
    [stack addArrangedSubview:[self labelWithText:@"账号操作" font:[NSFont systemFontOfSize:17 weight:NSFontWeightBold] color:NSColor.labelColor]];
    [stack addArrangedSubview:[self labelWithText:@"选中账号后，右侧检查器会直接执行启用/禁用、刷新令牌、解除冷却和删除。新增账号可以复制登录命令，或使用账号列表顶部的登录和导入入口。" font:[NSFont systemFontOfSize:13 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor]];
    NSStackView *buttons = [[NSStackView alloc] init];
    buttons.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    buttons.spacing = 8;
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"复制登录命令" symbol:@"doc.on.doc" selector:@selector(loginCommandAction:) primary:NO]];
    [stack addArrangedSubview:buttons];
    return card;
}

- (NSView *)quotaCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintGreaterThanOrEqualToConstant:128].active = YES;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    [header addArrangedSubview:[self labelWithText:@"额度状态" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [stack addArrangedSubview:header];
    [stack addArrangedSubview:[self emptyStateLabel:[self quotaTrackerSummaryText]]];

    for (NSDictionary *account in self.accounts) {
        NSString *name = CPString(account[@"name"]);
        NSStackView *row = [[NSStackView alloc] init];
        row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        row.alignment = NSLayoutAttributeTop;
        row.spacing = 10;
        row.translatesAutoresizingMaskIntoConstraints = NO;
        NSTextField *nameLabel = [self labelWithText:CPDisplayString(name) font:[NSFont systemFontOfSize:12 weight:NSFontWeightSemibold] color:NSColor.labelColor];
        [nameLabel.widthAnchor constraintEqualToConstant:34].active = YES;
        [row addArrangedSubview:nameLabel];

        NSStackView *lanes = [[NSStackView alloc] init];
        lanes.orientation = NSUserInterfaceLayoutOrientationVertical;
        lanes.alignment = NSLayoutAttributeWidth;
        lanes.spacing = 4;
        lanes.translatesAutoresizingMaskIntoConstraints = NO;
        [lanes setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
        [lanes setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
        NSProgressIndicator *primary = [self progressWithValue:[self quotaRemainingForAccountName:name weekly:NO]];
        NSProgressIndicator *secondary = [self progressWithValue:[self quotaRemainingForAccountName:name weekly:YES]];
        [lanes addArrangedSubview:[self quotaGroupWithTitle:@"5h" progress:primary value:[self quotaTextForAccountName:name weekly:NO]]];
        [lanes addArrangedSubview:[self quotaGroupWithTitle:@"7d" progress:secondary value:[self quotaTextForAccountName:name weekly:YES]]];
        [row addArrangedSubview:lanes];
        [lanes.widthAnchor constraintEqualToAnchor:row.widthAnchor constant:-44].active = YES;
        [stack addArrangedSubview:row];
        [row.widthAnchor constraintEqualToAnchor:stack.widthAnchor].active = YES;
    }
    if (!self.accounts.count) {
        [stack addArrangedSubview:[self emptyStateLabel:@"没有发现账号。请先添加账号或扫描账号目录。"]];
    }
    return card;
}

- (NSString *)quotaTrackerSummaryText {
    NSDictionary *tracker = CPDict(self.statusSnapshot[@"quota_tracker"]);
    if (!tracker.count) {
        return @"自动刷新：等待代理状态。";
    }
    BOOL enabled = CPBool(tracker[@"enabled"]);
    BOOL running = CPBool(tracker[@"running"]);
    BOOL inProgress = CPBool(tracker[@"in_progress"]);
    NSInteger interval = MAX(0, (NSInteger)CPDouble(tracker[@"interval"]));
    NSString *intervalText = interval >= 60
        ? [NSString stringWithFormat:@"%ld 分钟", (long)MAX(1, interval / 60)]
        : [NSString stringWithFormat:@"%ld 秒", (long)interval];
    NSDictionary *last = CPDict(tracker[@"last_result"]);
    NSString *lastText = CPDouble(tracker[@"last_run_at"]) > 0
        ? CPRelativeTime(tracker[@"last_run_at"])
        : @"尚未刷新";
    NSString *resultText = last.count
        ? [NSString stringWithFormat:@"成功 %@ / 失败 %@ / 跳过 %@",
           CPDisplayString(last[@"refreshed"]),
           CPDisplayString(last[@"failed"]),
           CPDisplayString(last[@"skipped"])]
        : CPDisplayString(tracker[@"last_error"]);
    NSString *state = enabled ? (running ? @"开启" : @"开启，等待任务启动") : @"关闭";
    if (inProgress) {
        state = @"刷新中";
    }
    return [NSString stringWithFormat:@"自动刷新：%@ · 间隔 %@ · 最近 %@ · %@",
            state,
            intervalText,
            lastText,
            resultText.length ? resultText : @"暂无结果"];
}

- (NSString *)codexModeTitle {
    return CPBool(self.statusSnapshot[@"enabled"]) ? @"代理模式" : @"直连模式";
}

- (NSString *)codexModeDetail {
    NSString *mode = CPString(self.statusSnapshot[@"mode"]);
    if ([mode isEqualToString:@"codex_pool_provider"]) {
        return @"账号池代理";
    }
    if ([mode isEqualToString:@"partial_chatgpt_backend"]) {
        return @"部分代理配置";
    }
    if ([mode isEqualToString:@"legacy_openai_provider"]) {
        return @"旧版代理配置";
    }
    if ([mode isEqualToString:@"direct"]) {
        return @"Codex 直连";
    }
    return CPDisplayString(mode);
}

- (NSString *)launchAgentTitle {
    BOOL installed = CPBool(self.statusSnapshot[@"installed"]);
    BOOL loaded = CPBool(self.statusSnapshot[@"loaded"]);
    if (installed && loaded) {
        return @"运行中";
    }
    if (installed) {
        return @"未加载";
    }
    return @"未安装";
}

- (NSString *)launchAgentDetail {
    BOOL installed = CPBool(self.statusSnapshot[@"installed"]);
    BOOL loaded = CPBool(self.statusSnapshot[@"loaded"]);
    if (installed && loaded) {
        return @"已安装并加载";
    }
    if (installed) {
        return @"已安装，待启动";
    }
    return @"未安装";
}

- (NSColor *)launchAgentColor {
    BOOL installed = CPBool(self.statusSnapshot[@"installed"]);
    BOOL loaded = CPBool(self.statusSnapshot[@"loaded"]);
    if (installed && loaded) {
        return NSColor.systemGreenColor;
    }
    return installed ? NSColor.systemOrangeColor : NSColor.systemRedColor;
}

- (NSView *)configCardsRow {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.spacing = 10;
    row.distribution = NSStackViewDistributionFillEqually;
    row.translatesAutoresizingMaskIntoConstraints = NO;
    BOOL runtimeMismatch = [self hasRuntimeManifestMismatch];
    BOOL versionMismatch = [self hasVersionMismatch];
    BOOL usageMismatch = [self hasUsageStorageMismatch];
    BOOL repairNeeded = CPBool(self.statusSnapshot[@"needs_repair"]) || runtimeMismatch || versionMismatch || usageMismatch;
    NSString *repairValue = @"正常";
    NSString *repairDetail = @"后台服务路径";
    NSColor *repairColor = NSColor.systemGreenColor;
    if (versionMismatch) {
        repairValue = @"需重开";
        repairDetail = @"版本号不一致";
        repairColor = NSColor.systemOrangeColor;
    } else if (runtimeMismatch) {
        repairValue = @"需同步";
        repairDetail = @"运行文件未同步";
        repairColor = NSColor.systemOrangeColor;
    } else if (usageMismatch) {
        repairValue = @"需迁移";
        repairDetail = @"Token 统计库未迁移";
        repairColor = NSColor.systemOrangeColor;
    } else if (repairNeeded) {
        repairValue = @"需要修复";
        repairDetail = @"后台服务路径不一致";
        repairColor = NSColor.systemRedColor;
    }
    [row addArrangedSubview:[self metricCardWithTitle:@"Codex 模式"
                                                value:[self codexModeTitle]
                                               detail:[self codexModeDetail]
                                                color:CPBool(self.statusSnapshot[@"enabled"]) ? NSColor.systemBlueColor : NSColor.systemOrangeColor]];
    [row addArrangedSubview:[self metricCardWithTitle:@"LaunchAgent"
                                                value:[self launchAgentTitle]
                                               detail:[self launchAgentDetail]
                                                color:[self launchAgentColor]]];
    [row addArrangedSubview:[self metricCardWithTitle:@"修复建议"
                                                value:repairValue
                                               detail:repairDetail
                                                color:repairColor]];
    return row;
}

- (NSView *)strategyCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;

    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    header.spacing = 10;
    [header addArrangedSubview:[self labelWithText:@"选择策略" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [header addArrangedSubview:[self labelWithText:[NSString stringWithFormat:@"额度优先 · %@", [self productModeTitle]] font:[NSFont systemFontOfSize:13 weight:NSFontWeightSemibold] color:NSColor.controlAccentColor]];
    [stack addArrangedSubview:header];

    [stack addArrangedSubview:[self emptyStateLabel:@"小腊肠会优先选择额度压力较低的账号。额度数据不完整时会自动保持可用账号轮换，不需要手动切换策略。"]];
    [stack addArrangedSubview:[self emptyStateLabel:[self selectionExplanationText]]];
    return card;
}

- (NSView *)pathsCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];
    [stack addArrangedSubview:[self labelWithText:@"路径与诊断" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"Codex CLI" value:CPBool(self.statusSnapshot[@"codex_cli_found"]) ? CPDisplayString(self.statusSnapshot[@"codex_cli"]) : @"未找到"]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"运行目录" value:CPDisplayString(self.statusSnapshot[@"runtime_dir"])]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"源码/资源" value:CPDisplayString(self.statusSnapshot[@"source_dir"])]];
    NSStackView *buttons = [[NSStackView alloc] init];
    buttons.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    buttons.spacing = 6;
    buttons.distribution = NSStackViewDistributionFillEqually;
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"应用更新" symbol:@"arrow.down.app" selector:@selector(applyUpdateAction:) primary:NO]];
    [stack addArrangedSubview:buttons];
    return card;
}

- (NSView *)updateDiagnosticsCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];
    [stack addArrangedSubview:[self labelWithText:@"更新诊断" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    [stack addArrangedSubview:[self versionDiagnosticsGridCompact:NO]];
    NSString *manifestError = CPString(self.statusSnapshot[@"manifest_error"]);
    if (manifestError.length) {
        [stack addArrangedSubview:[self emptyStateLabel:manifestError]];
    }
    return card;
}

- (NSView *)versionDiagnosticsGridCompact:(BOOL)compact {
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = compact ? 4 : 6;
    NSString *proxyVersion = CPString(self.statusSnapshot[@"proxy_version"]);
    if (!proxyVersion.length) {
        proxyVersion = CPString(self.statusSnapshot[@"version"]);
    }
    [stack addArrangedSubview:[self infoRowWithTitle:@"前台版本" value:CPDisplayString(self.frontendVersion)]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"内置版本" value:CPDisplayString(self.statusSnapshot[@"bundle_version"])]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"运行版本" value:CPDisplayString(self.statusSnapshot[@"runtime_version"])]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"后台版本" value:CPDisplayString(proxyVersion)]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"Manifest" value:CPBool(self.statusSnapshot[@"manifest_ok"]) ? @"一致" : @"需检查"]];
    if (!compact) {
        NSDictionary *manifest = [self runtimeManifestSnapshot];
        NSDictionary<NSString *, NSString *> *titles = @{
            @"changed": @"变更文件",
            @"missing": @"缺失文件",
            @"extra": @"多余文件",
            @"expected_missing": @"内置缺失",
            @"observed_missing": @"运行缺失",
        };
        for (NSString *key in @[@"changed", @"missing", @"extra", @"expected_missing", @"observed_missing"]) {
            NSArray *items = CPArray(manifest[key]);
            if (items.count == 0) {
                continue;
            }
            NSMutableArray<NSString *> *names = [NSMutableArray array];
            for (id item in items) {
                NSString *name = CPString(item);
                if (name.length) {
                    [names addObject:name];
                }
            }
            if (names.count) {
                [stack addArrangedSubview:[self infoRowWithTitle:titles[key] value:[names componentsJoinedByString:@", "]]];
            }
        }
        NSString *manifestError = CPString(self.statusSnapshot[@"manifest_error"]);
        if (!manifestError.length) {
            manifestError = CPString(manifest[@"error"]);
        }
        if (manifestError.length) {
            [stack addArrangedSubview:[self infoRowWithTitle:@"Manifest 错误" value:manifestError]];
        }
        [stack addArrangedSubview:[self infoRowWithTitle:@"LaunchAgent" value:CPDisplayString(self.statusSnapshot[@"installed_program"])]];
    }
    return stack;
}

- (NSView *)diagnosticsCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];
    [stack addArrangedSubview:[self labelWithText:@"诊断操作" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    [stack addArrangedSubview:[self emptyStateLabel:@"诊断操作已集中到设置窗口的“诊断”页。"]];
    return card;
}

- (NSView *)logCardWithHeight:(CGFloat)height {
    return [self logCardWithHeight:height actions:NO];
}

- (NSView *)logCardWithHeight:(CGFloat)height actions:(BOOL)actions {
    NSView *card = [self cardViewWithBackground:NSColor.textBackgroundColor];
    card.wantsLayer = YES;
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintEqualToConstant:height].active = YES;

    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 6;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 10, 12)];
    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    header.spacing = 6;
    [header addArrangedSubview:[self labelWithText:@"活动日志" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [stack addArrangedSubview:header];

    NSScrollView *scroll = [[NSScrollView alloc] init];
    scroll.borderType = NSNoBorder;
    scroll.drawsBackground = NO;
    scroll.hasVerticalScroller = YES;
    self.outputView = self.outputView ?: [[NSTextView alloc] init];
    self.outputView.editable = NO;
    self.outputView.drawsBackground = NO;
    self.outputView.textColor = NSColor.labelColor;
    self.outputView.font = [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular];
    scroll.documentView = self.outputView;
    [stack addArrangedSubview:scroll];
    [scroll.heightAnchor constraintGreaterThanOrEqualToConstant:MAX(32, height - (actions ? 82 : 52))].active = YES;
    return card;
}

- (NSView *)recentRequestsCard {
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeWidth;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [stack.heightAnchor constraintEqualToConstant:190].active = YES;

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    header.spacing = 6;
    [header addArrangedSubview:[self labelWithText:@"最近请求" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [header addArrangedSubview:[self smallButtonWithTitle:@"清空" symbol:@"trash" selector:@selector(clearRecentRequestsAction:)]];
    [stack addArrangedSubview:header];

    NSView *table = [[NSView alloc] init];
    table.translatesAutoresizingMaskIntoConstraints = NO;
    [table.heightAnchor constraintEqualToConstant:144].active = YES;
    [stack addArrangedSubview:table];
    [table.widthAnchor constraintEqualToAnchor:stack.widthAnchor].active = YES;

    NSArray *items = CPArray(self.statusSnapshot[@"recent_requests"]);
    NSInteger count = MIN((NSInteger)items.count, 10);
    if (count == 0) {
        NSTextField *empty = [self emptyStateLabel:@"暂无最近请求。代理收到请求后会显示在这里。"];
        [table addSubview:empty];
        [NSLayoutConstraint activateConstraints:@[
            [empty.leadingAnchor constraintEqualToAnchor:table.leadingAnchor constant:8],
            [empty.trailingAnchor constraintEqualToAnchor:table.trailingAnchor constant:-8],
            [empty.centerYAnchor constraintEqualToAnchor:table.centerYAnchor],
        ]];
        return stack;
    }

    NSStackView *columns = [[NSStackView alloc] init];
    columns.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    columns.alignment = NSLayoutAttributeTop;
    columns.distribution = NSStackViewDistributionFillEqually;
    columns.spacing = 12;
    columns.translatesAutoresizingMaskIntoConstraints = NO;
    [table addSubview:columns];
    [self pinView:columns toView:table insets:NSEdgeInsetsMake(0, 0, 0, 0)];

    for (NSInteger column = 0; column < 2; column++) {
        NSStackView *rows = [[NSStackView alloc] init];
        rows.orientation = NSUserInterfaceLayoutOrientationVertical;
        rows.alignment = NSLayoutAttributeWidth;
        rows.spacing = 0;
        rows.translatesAutoresizingMaskIntoConstraints = NO;
        [columns addArrangedSubview:rows];

        NSView *head = [self recentRequestRowWithTime:@"时间" account:@"账号" status:@"状态" path:@"路径" header:YES];
        [rows addArrangedSubview:head];
        [head.widthAnchor constraintEqualToAnchor:rows.widthAnchor].active = YES;

        NSInteger start = column * 5;
        NSInteger end = MIN(start + 5, count);
        for (NSInteger i = start; i < end; i++) {
            NSDictionary *item = CPDict(items[i]);
            NSView *row = [self recentRequestRowWithTime:[self requestTimeText:item[@"at"]]
                                                 account:CPDisplayString(item[@"account"])
                                                  status:CPDisplayString(item[@"status"])
                                                    path:CPDisplayString(item[@"path"])
                                                  header:NO];
            [rows addArrangedSubview:row];
            [row.widthAnchor constraintEqualToAnchor:rows.widthAnchor].active = YES;
        }
    }
    return stack;
}

- (NSView *)recentRequestRowWithTime:(NSString *)time account:(NSString *)account status:(NSString *)status path:(NSString *)path header:(BOOL)header {
    NSView *row = [[NSView alloc] init];
    row.translatesAutoresizingMaskIntoConstraints = NO;
    [row.heightAnchor constraintEqualToConstant:header ? 24 : 25].active = YES;

    NSTextField *timeLabel = [self labelWithText:time font:[NSFont monospacedSystemFontOfSize:10 weight:header ? NSFontWeightSemibold : NSFontWeightRegular] color:header ? NSColor.secondaryLabelColor : NSColor.labelColor];
    NSTextField *accountLabel = [self labelWithText:account font:[NSFont monospacedSystemFontOfSize:10 weight:header ? NSFontWeightSemibold : NSFontWeightRegular] color:header ? NSColor.secondaryLabelColor : NSColor.labelColor];
    BOOL statusOK = [status hasPrefix:@"1"] || [status hasPrefix:@"2"];
    NSTextField *statusLabel = [self labelWithText:status font:[NSFont monospacedSystemFontOfSize:10 weight:header ? NSFontWeightSemibold : NSFontWeightRegular] color:statusOK ? NSColor.systemGreenColor : (header ? NSColor.secondaryLabelColor : NSColor.systemOrangeColor)];
    NSTextField *pathLabel = [self labelWithText:path font:[NSFont monospacedSystemFontOfSize:9 weight:NSFontWeightRegular] color:header ? NSColor.secondaryLabelColor : NSColor.secondaryLabelColor];
    timeLabel.alignment = NSTextAlignmentLeft;
    accountLabel.alignment = NSTextAlignmentLeft;
    statusLabel.alignment = NSTextAlignmentCenter;
    pathLabel.alignment = NSTextAlignmentLeft;
    pathLabel.lineBreakMode = NSLineBreakByTruncatingMiddle;
    pathLabel.toolTip = header ? nil : path;
    [row addSubview:timeLabel];
    [row addSubview:accountLabel];
    [row addSubview:statusLabel];
    [row addSubview:pathLabel];
    [NSLayoutConstraint activateConstraints:@[
        [timeLabel.leadingAnchor constraintEqualToAnchor:row.leadingAnchor constant:4],
        [timeLabel.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
        [timeLabel.widthAnchor constraintEqualToConstant:52],

        [accountLabel.leadingAnchor constraintEqualToAnchor:timeLabel.trailingAnchor constant:8],
        [accountLabel.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
        [accountLabel.widthAnchor constraintEqualToConstant:30],

        [statusLabel.leadingAnchor constraintEqualToAnchor:accountLabel.trailingAnchor constant:8],
        [statusLabel.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
        [statusLabel.widthAnchor constraintEqualToConstant:34],

        [pathLabel.leadingAnchor constraintEqualToAnchor:statusLabel.trailingAnchor constant:8],
        [pathLabel.trailingAnchor constraintEqualToAnchor:row.trailingAnchor constant:-4],
        [pathLabel.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
    ]];
    return row;
}

#pragma mark - View Helpers

- (NSView *)constrainedContentView:(NSView *)content {
    return [self constrainedContentView:content width:450];
}

- (NSView *)constrainedContentView:(NSView *)content width:(CGFloat)width {
    NSView *container = [[NSView alloc] init];
    container.translatesAutoresizingMaskIntoConstraints = NO;
    content.translatesAutoresizingMaskIntoConstraints = NO;
    [container addSubview:content];
    [NSLayoutConstraint activateConstraints:@[
        [content.topAnchor constraintEqualToAnchor:container.topAnchor],
        [content.bottomAnchor constraintEqualToAnchor:container.bottomAnchor],
        [content.centerXAnchor constraintEqualToAnchor:container.centerXAnchor],
        [content.widthAnchor constraintEqualToConstant:width],
        [content.widthAnchor constraintLessThanOrEqualToAnchor:container.widthAnchor],
    ]];
    return container;
}

- (NSTextField *)labelWithText:(NSString *)text font:(NSFont *)font color:(NSColor *)color {
    NSTextField *label = [NSTextField labelWithString:text ?: @""];
    label.font = font;
    label.textColor = color;
    label.lineBreakMode = NSLineBreakByTruncatingTail;
    label.translatesAutoresizingMaskIntoConstraints = NO;
    [label setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    return label;
}

- (NSTextField *)emptyStateLabel:(NSString *)text {
    NSTextField *label = [self labelWithText:text font:[NSFont systemFontOfSize:13 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
    label.lineBreakMode = NSLineBreakByWordWrapping;
    label.maximumNumberOfLines = 0;
    return label;
}

- (NSView *)cardView {
    return [self cardViewWithBackground:NSColor.clearColor];
}

- (NSView *)cardViewWithBackground:(NSColor *)background {
    CPThemedView *view = [[CPThemedView alloc] init];
    view.translatesAutoresizingMaskIntoConstraints = NO;
    view.wantsLayer = YES;
    view.layer.cornerRadius = 0;
    view.cpBackgroundColor = background ?: NSColor.clearColor;
    view.cpBorderColor = NSColor.clearColor;
    view.layer.borderWidth = 0;
    view.cpShadowColor = NSColor.blackColor;
    view.layer.shadowOpacity = 0;
    view.layer.shadowOffset = CGSizeMake(0, -1);
    view.layer.shadowRadius = 4;
    [view setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    [view setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    return view;
}

- (NSView *)statusDotWithColor:(NSColor *)color {
    CPThemedView *dot = [[CPThemedView alloc] init];
    dot.translatesAutoresizingMaskIntoConstraints = NO;
    dot.wantsLayer = YES;
    dot.layer.cornerRadius = 4;
    dot.cpBackgroundColor = color;
    [dot.widthAnchor constraintEqualToConstant:8].active = YES;
    [dot.heightAnchor constraintEqualToConstant:8].active = YES;
    return dot;
}

- (NSButton *)navigationButtonWithTitle:(NSString *)title symbol:(NSString *)symbol tag:(NSInteger)tag {
    NSButton *button = [NSButton buttonWithTitle:@"" target:self action:@selector(navigationAction:)];
    button.tag = tag;
    button.bordered = NO;
    button.contentTintColor = NSColor.labelColor;
    button.translatesAutoresizingMaskIntoConstraints = NO;
    button.wantsLayer = YES;
    button.layer.cornerRadius = 9;
    button.layer.masksToBounds = YES;

    NSImageView *iconView = [[NSImageView alloc] init];
    iconView.translatesAutoresizingMaskIntoConstraints = NO;
    iconView.imageScaling = NSImageScaleProportionallyDown;
    iconView.contentTintColor = NSColor.labelColor;
    NSImage *image = [self symbolImageNamed:symbol];
    if (image) {
        image.template = YES;
        iconView.image = image;
    }

    NSTextField *titleLabel = [self labelWithText:title
                                             font:[NSFont systemFontOfSize:13 weight:NSFontWeightSemibold]
                                            color:NSColor.labelColor];
    titleLabel.alignment = NSTextAlignmentLeft;
    titleLabel.maximumNumberOfLines = 1;

    [button addSubview:iconView];
    [button addSubview:titleLabel];
    [NSLayoutConstraint activateConstraints:@[
        [iconView.centerXAnchor constraintEqualToAnchor:button.leadingAnchor constant:18],
        [iconView.centerYAnchor constraintEqualToAnchor:button.centerYAnchor],
        [iconView.widthAnchor constraintEqualToConstant:17],
        [iconView.heightAnchor constraintEqualToConstant:17],

        [titleLabel.leadingAnchor constraintEqualToAnchor:button.leadingAnchor constant:38],
        [titleLabel.trailingAnchor constraintEqualToAnchor:button.trailingAnchor constant:-8],
        [titleLabel.centerYAnchor constraintEqualToAnchor:button.centerYAnchor],
    ]];
    [self.navIconViews addObject:iconView];
    [self.navTitleLabels addObject:titleLabel];

    [button.widthAnchor constraintEqualToConstant:90].active = YES;
    [button.heightAnchor constraintEqualToConstant:34].active = YES;
    return button;
}

- (NSButton *)actionButtonWithTitle:(NSString *)title symbol:(NSString *)symbol selector:(SEL)selector primary:(BOOL)primary {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:selector];
    button.bezelStyle = primary ? NSBezelStyleTexturedRounded : NSBezelStyleRounded;
    button.controlSize = NSControlSizeSmall;
    button.imagePosition = NSImageLeading;
    button.font = [NSFont systemFontOfSize:12 weight:primary ? NSFontWeightSemibold : NSFontWeightRegular];
    button.translatesAutoresizingMaskIntoConstraints = NO;
    button.toolTip = title;
    NSImage *image = [self symbolImageNamed:symbol];
    if (image) {
        button.image = image;
    }
    [button.heightAnchor constraintEqualToConstant:28].active = YES;
    [button setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    [button setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    [self.buttons addObject:button];
    return button;
}

- (NSButton *)smallButtonWithTitle:(NSString *)title symbol:(NSString *)symbol selector:(SEL)selector {
    NSButton *button = [self actionButtonWithTitle:title symbol:symbol selector:selector primary:NO];
    button.controlSize = NSControlSizeSmall;
    return button;
}

- (NSImage *)symbolImageNamed:(NSString *)name {
    if (@available(macOS 11.0, *)) {
        return [NSImage imageWithSystemSymbolName:name accessibilityDescription:name];
    }
    return nil;
}

- (NSImage *)brandIconImage {
    NSArray<NSString *> *paths = @[
        [self.resourceRuntimeDir stringByAppendingPathComponent:@"static/icons/dog-head.png"],
        [self.resourceRuntimeDir stringByAppendingPathComponent:@"static/icons/icon-192.png"],
        [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"AppIcon.icns"],
    ];
    for (NSString *path in paths) {
        NSImage *image = [[NSImage alloc] initWithContentsOfFile:path];
        if (image) {
            image.accessibilityDescription = @"小腊肠";
            return image;
        }
    }
    return nil;
}

- (NSView *)sidebarBrandIconView {
    NSView *container = [[NSView alloc] init];
    container.translatesAutoresizingMaskIntoConstraints = NO;
    [container.widthAnchor constraintEqualToConstant:102].active = YES;
    [container.heightAnchor constraintEqualToConstant:64].active = YES;

    NSImage *image = [self brandIconImage];
    if (image) {
        NSImageView *imageView = [[NSImageView alloc] init];
        imageView.image = image;
        imageView.imageScaling = NSImageScaleProportionallyUpOrDown;
        imageView.translatesAutoresizingMaskIntoConstraints = NO;
        imageView.accessibilityLabel = @"小腊肠";
        [container addSubview:imageView];
        [NSLayoutConstraint activateConstraints:@[
            [imageView.centerXAnchor constraintEqualToAnchor:container.centerXAnchor],
            [imageView.centerYAnchor constraintEqualToAnchor:container.centerYAnchor],
            [imageView.widthAnchor constraintEqualToConstant:64],
            [imageView.heightAnchor constraintEqualToConstant:64],
        ]];
    } else {
        NSTextField *fallback = [self labelWithText:@"Codex" font:[NSFont systemFontOfSize:15 weight:NSFontWeightBold] color:NSColor.labelColor];
        fallback.alignment = NSTextAlignmentCenter;
        [container addSubview:fallback];
        [NSLayoutConstraint activateConstraints:@[
            [fallback.centerXAnchor constraintEqualToAnchor:container.centerXAnchor],
            [fallback.centerYAnchor constraintEqualToAnchor:container.centerYAnchor],
        ]];
    }
    return container;
}

- (NSView *)metricCardWithTitle:(NSString *)title value:(NSString *)value detail:(NSString *)detail color:(NSColor *)color {
    NSStackView *card = [[NSStackView alloc] init];
    card.orientation = NSUserInterfaceLayoutOrientationVertical;
    card.alignment = NSLayoutAttributeCenterX;
    card.spacing = 2;
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintEqualToConstant:58].active = YES;
    [card.widthAnchor constraintGreaterThanOrEqualToConstant:96].active = YES;

    NSTextField *titleLabel = [self labelWithText:title font:[NSFont systemFontOfSize:10 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor];
    NSTextField *valueLabel = [self labelWithText:value ?: @"-" font:[NSFont systemFontOfSize:18 weight:NSFontWeightBold] color:color ?: NSColor.labelColor];
    BOOL hasDetail = detail.length > 0;
    NSTextField *detailLabel = hasDetail ? [self labelWithText:detail font:[NSFont systemFontOfSize:10 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor] : nil;
    for (NSTextField *label in (detailLabel ? @[titleLabel, valueLabel, detailLabel] : @[titleLabel, valueLabel])) {
        label.alignment = NSTextAlignmentCenter;
        label.maximumNumberOfLines = 1;
        label.lineBreakMode = NSLineBreakByTruncatingTail;
        [label setContentCompressionResistancePriority:NSLayoutPriorityDefaultHigh forOrientation:NSLayoutConstraintOrientationVertical];
        [card addArrangedSubview:label];
    }
    return card;
}

- (NSView *)infoRowWithTitle:(NSString *)title value:(NSString *)value {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.spacing = 12;
    row.alignment = NSLayoutAttributeFirstBaseline;
    NSTextField *left = [self labelWithText:title font:[NSFont systemFontOfSize:12 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor];
    [left.widthAnchor constraintEqualToConstant:86].active = YES;
    NSTextField *right = [self labelWithText:value font:[NSFont monospacedSystemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.labelColor];
    right.lineBreakMode = NSLineBreakByTruncatingMiddle;
    [row addArrangedSubview:left];
    [row addArrangedSubview:right];
    return row;
}

- (NSView *)accountInspectorInfoRowWithTitle:(NSString *)title value:(NSString *)value {
    NSView *row = [[NSView alloc] init];
    row.translatesAutoresizingMaskIntoConstraints = NO;
    [row.heightAnchor constraintEqualToConstant:25].active = YES;

    NSTextField *left = [self labelWithText:title font:[NSFont systemFontOfSize:12 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor];
    NSTextField *right = [self labelWithText:value font:[NSFont monospacedSystemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.labelColor];
    left.alignment = NSTextAlignmentLeft;
    right.alignment = NSTextAlignmentCenter;
    right.lineBreakMode = NSLineBreakByTruncatingMiddle;
    right.toolTip = value;
    [left setContentCompressionResistancePriority:NSLayoutPriorityRequired forOrientation:NSLayoutConstraintOrientationHorizontal];
    [right setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];

    [row addSubview:left];
    [row addSubview:right];
    [NSLayoutConstraint activateConstraints:@[
        [left.leadingAnchor constraintEqualToAnchor:row.leadingAnchor],
        [left.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
        [left.widthAnchor constraintEqualToConstant:88],

        [right.leadingAnchor constraintEqualToAnchor:left.trailingAnchor constant:6],
        [right.trailingAnchor constraintEqualToAnchor:row.trailingAnchor],
        [right.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
    ]];
    return row;
}

- (NSProgressIndicator *)progressWithValue:(double)value {
    NSProgressIndicator *progress = [[NSProgressIndicator alloc] init];
    progress.indeterminate = NO;
    progress.minValue = 0;
    progress.maxValue = 100;
    progress.doubleValue = MAX(0, MIN(100, value));
    progress.controlSize = NSControlSizeSmall;
    progress.translatesAutoresizingMaskIntoConstraints = NO;
    [progress.widthAnchor constraintGreaterThanOrEqualToConstant:96].active = YES;
    [progress setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    [progress setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    return progress;
}

- (NSView *)quotaGroupWithTitle:(NSString *)title progress:(NSProgressIndicator *)progress value:(NSString *)value {
    NSStackView *group = [[NSStackView alloc] init];
    group.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    group.spacing = 8;
    group.alignment = NSLayoutAttributeCenterY;
    group.distribution = NSStackViewDistributionFill;
    group.translatesAutoresizingMaskIntoConstraints = NO;
    [group.heightAnchor constraintEqualToConstant:22].active = YES;
    NSTextField *titleLabel = [self labelWithText:title font:[NSFont systemFontOfSize:12 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor];
    titleLabel.alignment = NSTextAlignmentLeft;
    [titleLabel.widthAnchor constraintEqualToConstant:22].active = YES;
    [group addArrangedSubview:titleLabel];
    [group addArrangedSubview:progress];
    NSTextField *valueLabel = [self labelWithText:value font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
    valueLabel.alignment = NSTextAlignmentRight;
    [valueLabel.widthAnchor constraintEqualToConstant:44].active = YES;
    [group addArrangedSubview:valueLabel];
    return group;
}

- (void)pinView:(NSView *)view toView:(NSView *)parent insets:(NSEdgeInsets)insets {
    [NSLayoutConstraint activateConstraints:@[
        [view.leadingAnchor constraintEqualToAnchor:parent.leadingAnchor constant:insets.left],
        [view.trailingAnchor constraintEqualToAnchor:parent.trailingAnchor constant:-insets.right],
        [view.topAnchor constraintEqualToAnchor:parent.topAnchor constant:insets.top],
        [view.bottomAnchor constraintEqualToAnchor:parent.bottomAnchor constant:-insets.bottom],
    ]];
}

- (void)addSpacerToStack:(NSStackView *)stack height:(CGFloat)height {
    NSView *spacer = [[NSView alloc] init];
    spacer.translatesAutoresizingMaskIntoConstraints = NO;
    [spacer.heightAnchor constraintEqualToConstant:height].active = YES;
    [stack addArrangedSubview:spacer];
}

- (void)addDividerToStack:(NSStackView *)stack top:(CGFloat)top bottom:(CGFloat)bottom {
    [self addSpacerToStack:stack height:top];
    NSBox *divider = [[NSBox alloc] init];
    divider.boxType = NSBoxSeparator;
    divider.translatesAutoresizingMaskIntoConstraints = NO;
    [stack addArrangedSubview:divider];
    [divider.widthAnchor constraintEqualToAnchor:stack.widthAnchor].active = YES;
    [self addSpacerToStack:stack height:bottom];
}

#pragma mark - Data Refresh

- (NSDictionary *)snapshotPayloadRefreshingQuota:(BOOL)refreshQuota
                              quotaRefreshResult:(NSDictionary **)quotaRefreshResult
                                     proxyOnline:(BOOL *)proxyOnline {
    NSDictionary *localStatus = [self runPythonJSONSync:@[@"status"] rawText:nil];
    NSDictionary *remoteStatus = [self fetchJSONPath:@"/api/status" method:@"GET" timeout:2.0];
    BOOL isProxyOnline = [remoteStatus isKindOfClass:NSDictionary.class] && CPBool(remoteStatus[@"running"]);
    if (proxyOnline) {
        *proxyOnline = isProxyOnline;
    }

    NSMutableDictionary *mergedStatus = [localStatus isKindOfClass:NSDictionary.class] ? [localStatus mutableCopy] : [NSMutableDictionary dictionary];
    if (isProxyOnline) {
        [mergedStatus addEntriesFromDictionary:remoteStatus];
        id remoteSelection = [self fetchJSONPath:@"/api/selection" method:@"GET" timeout:2.0];
        if ([remoteSelection isKindOfClass:NSDictionary.class]) {
            mergedStatus[@"selection"] = remoteSelection;
        }
    } else if (!mergedStatus.count) {
        mergedStatus[@"running"] = @NO;
    }
    NSDictionary *status = mergedStatus;

    NSArray *accounts = @[];
    NSDictionary *quota = @{};
    NSDictionary *tokenUsage = @{};
    if (isProxyOnline) {
        if (refreshQuota) {
            id refreshResult = [self fetchJSONPath:@"/api/quota/refresh" method:@"POST" timeout:12.0];
            if ([refreshResult isKindOfClass:NSDictionary.class] && quotaRefreshResult) {
                *quotaRefreshResult = refreshResult;
            }
        }
        id remoteAccounts = [self fetchJSONPath:@"/api/accounts" method:@"GET" timeout:2.0];
        if ([remoteAccounts isKindOfClass:NSArray.class]) {
            accounts = remoteAccounts;
        }
        id remoteQuota = [self fetchJSONPath:@"/api/quota" method:@"GET" timeout:2.0];
        if ([remoteQuota isKindOfClass:NSDictionary.class]) {
            quota = remoteQuota;
        }
        id remoteTokenUsage = [self fetchJSONPath:@"/api/token-usage?daily_days=371" method:@"GET" timeout:2.0];
        if ([remoteTokenUsage isKindOfClass:NSDictionary.class]) {
            tokenUsage = remoteTokenUsage;
        }
    }
    if (!accounts.count) {
        NSDictionary *local = [self runPythonJSONSync:@[@"list-accounts"] rawText:nil];
        accounts = CPArray(local[@"accounts"]);
        if (!status[@"total_accounts"]) {
            NSMutableDictionary *merged = [status mutableCopy] ?: [NSMutableDictionary dictionary];
            merged[@"total_accounts"] = local[@"total_accounts"] ?: @(accounts.count);
            merged[@"active_accounts"] = local[@"active_accounts"] ?: @0;
            status = merged;
        }
    }

    return @{
        @"status": status ?: @{},
        @"accounts": accounts ?: @[],
        @"quota": quota ?: @{},
        @"tokenUsage": tokenUsage ?: @{},
    };
}

- (void)applySnapshotPayload:(NSDictionary *)payload {
    self.statusSnapshot = CPDict(payload[@"status"]);
    self.accounts = CPArray(payload[@"accounts"]);
    self.quotaSnapshot = CPDict(payload[@"quota"]);
    self.tokenUsageSnapshot = CPDict(payload[@"tokenUsage"]);
    if (!self.selectedAccountName.length && self.accounts.count) {
        self.selectedAccountName = CPString(self.accounts.firstObject[@"name"]);
    }
}

- (void)applySilentSnapshotPayload:(NSDictionary *)payload {
    NSString *selectedBefore = self.selectedAccountName ?: @"";
    [self applySnapshotPayload:payload];
    if (selectedBefore.length) {
        self.selectedAccountName = selectedBefore;
    }
    if (self.window) {
        [self updateStatusViews];
        [self updateHeaderText];
    }
    if (self.accountTable) {
        [self reloadAccountTableSelection];
    }
}

- (void)refreshSnapshots:(id)sender {
    if (self.busy || self.refreshInFlight) {
        return;
    }
    self.refreshInFlight = YES;
    [self setBusy:YES message:@"正在刷新状态..."];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSDictionary *quotaRefreshResult = nil;
        BOOL proxyOnline = NO;
        NSDictionary *payload = [self snapshotPayloadRefreshingQuota:YES
                                                   quotaRefreshResult:&quotaRefreshResult
                                                          proxyOnline:&proxyOnline];

        dispatch_async(dispatch_get_main_queue(), ^{
            self.refreshInFlight = NO;
            [self applySnapshotPayload:payload];
            if (self.window) {
                [self updateStatusViews];
                [self renderActiveSection];
            }
            NSString *message = proxyOnline
                ? (quotaRefreshResult ? @"状态和额度已刷新" : @"状态已刷新，额度刷新失败")
                : @"状态已刷新";
            [self setBusy:NO message:message];
            if (self.settingsController.window) {
                [self.settingsController refresh:nil];
            }
        });
    });
}

- (void)autoRefreshSnapshots:(id)sender {
    if (self.busy || self.refreshInFlight) {
        return;
    }
    self.refreshInFlight = YES;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        BOOL proxyOnline = NO;
        NSDictionary *payload = [self snapshotPayloadRefreshingQuota:NO
                                                   quotaRefreshResult:nil
                                                          proxyOnline:&proxyOnline];
        dispatch_async(dispatch_get_main_queue(), ^{
            self.refreshInFlight = NO;
            if (self.busy) {
                return;
            }
            [self applySilentSnapshotPayload:payload];
        });
    });
}

- (void)refreshQuotaAction:(id)sender {
    [self refreshSnapshots:sender];
}

- (void)updateStatusViews {
    BOOL running = CPBool(self.statusSnapshot[@"running"]);
    NSString *online = running ? @"代理在线" : @"代理离线";
    if ([self hasVersionMismatch]) {
        online = @"版本不同步";
    } else if ([self hasRuntimeManifestMismatch]) {
        online = @"运行文件未同步";
    }
    NSString *accounts = [NSString stringWithFormat:@"%@/%@ 可用",
                          CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                          CPDisplayString(self.statusSnapshot[@"total_accounts"])];
    NSString *sidebarState = running ? @"在线" : @"离线";
    if ([self hasVersionMismatch]) {
        sidebarState = @"需重开";
    } else if ([self hasRuntimeManifestMismatch]) {
        sidebarState = @"需同步";
    }
    self.subtitleLabel.stringValue = [NSString stringWithFormat:@"%@ · %@ · %@", online, accounts, [self codexModeDetail]];
    self.sidebarStatusLabel.stringValue = [NSString stringWithFormat:@"%@ · %@/%@ 可用",
                                           sidebarState,
                                           CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                                           CPDisplayString(self.statusSnapshot[@"total_accounts"])];
}

- (void)updateHeaderText {
    NSDictionary *titles = @{
        @"overview": @[@"总览", @"额度和 Token 活动。"],
        @"accounts": @[@"账号", @"代理、账号池和运行状态。"],
        @"config": @[@"配置", @"额度优先、代理模式和运行诊断。"],
        @"logs": @[@"日志", @"查看操作结果、日志和路径诊断。"],
    };
    NSArray *pair = titles[self.activeSection] ?: titles[@"overview"];
    self.titleLabel.stringValue = pair[0];
    BOOL running = CPBool(self.statusSnapshot[@"running"]);
    NSString *state = running ? @"代理在线" : @"代理离线";
    if ([self hasVersionMismatch]) {
        state = @"版本不同步";
    } else if ([self hasRuntimeManifestMismatch]) {
        state = @"运行文件未同步";
    }
    self.subtitleLabel.stringValue = [NSString stringWithFormat:@"%@ · %@", state, pair[1]];
}

#pragma mark - Actions

- (NSString *)friendlyErrorTextForResult:(NSDictionary *)result fallback:(NSString *)fallback {
    NSString *error = CPString(result[@"error"]);
    if ([error isEqualToString:@"codex_cli_missing"] || [error isEqualToString:@"codex_app_missing"]) {
        NSString *hint = CPString(result[@"codex_cli_error"]);
        return hint.length ? hint : @"请先安装 Codex App。";
    }
    if (error.length) {
        return error;
    }
    return fallback ?: @"";
}

- (BOOL)showCodexMissingAlertIfNeededForCLI:(BOOL)needsCLI openApp:(BOOL)needsApp {
    id cliValue = self.statusSnapshot[@"codex_cli_found"];
    id appValue = self.statusSnapshot[@"codex_app_found"];
    BOOL cliKnownMissing = needsCLI && cliValue && !CPBool(cliValue);
    BOOL appKnownMissing = needsApp && appValue && !CPBool(appValue);
    if (!cliKnownMissing && !appKnownMissing) {
        return NO;
    }

    NSString *message = appKnownMissing ? @"未找到 Codex App" : @"未找到 Codex CLI";
    NSString *hint = CPString(self.statusSnapshot[@"codex_cli_error"]);
    if (!hint.length || appKnownMissing) {
        hint = appKnownMissing ? @"请先安装 Codex App，再使用“打开 Codex”。" : @"请先安装 Codex App，或确保 codex 命令在 PATH 中。";
    }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = message;
    alert.informativeText = hint;
    [alert addButtonWithTitle:@"知道了"];
    [alert runModal];
    [self appendLog:[NSString stringWithFormat:@"%@：%@", message, hint]];
    self.footerStatusLabel.stringValue = hint;
    return YES;
}

- (void)performAction:(NSArray<NSString *> *)args label:(NSString *)label refreshAfter:(BOOL)refreshAfter {
    [self performAction:args label:label refreshAfter:refreshAfter fromBundle:NO];
}

- (void)performAction:(NSArray<NSString *> *)args label:(NSString *)label refreshAfter:(BOOL)refreshAfter fromBundle:(BOOL)fromBundle {
    if (self.busy) {
        return;
    }
    [self setBusy:YES message:[NSString stringWithFormat:@"正在执行：%@...", label]];
    [self appendLog:[NSString stringWithFormat:@"$ %@", label]];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSString *raw = nil;
        NSDictionary *result = fromBundle
            ? [self runBundleActionJSONSync:args rawText:&raw]
            : [self runPythonJSONSync:args rawText:&raw];
        NSString *body = CPPrettyJSON(result ?: @{@"output": raw ?: @""});
        [self writeResultWithTitle:label body:body];
        dispatch_async(dispatch_get_main_queue(), ^{
            [self appendLog:body];
            NSString *errorText = [self friendlyErrorTextForResult:result ?: @{} fallback:nil];
            BOOL failed = errorText.length > 0 || [result[@"exit_code"] integerValue] != 0;
            [self setBusy:NO message:failed
                ? [NSString stringWithFormat:@"%@ 失败：%@", label, errorText.length ? errorText : @"执行失败"]
                : [NSString stringWithFormat:@"%@ 已完成", label]];
            if (refreshAfter) {
                [self refreshSnapshots:nil];
            }
        });
    });
}

- (void)statusAction:(id)sender {
    [self refreshSnapshots:nil];
}

- (void)showSettings:(id)sender {
    if (!self.settingsController) {
        self.settingsController = [[SettingsWindowController alloc] initWithOwner:self];
    }
    [self.settingsController show];
}

- (void)repairAction:(id)sender {
    [self performAction:@[@"repair"] label:@"启动/修复/更新后台" refreshAfter:YES fromBundle:YES];
}

- (void)continueSetupAction:(id)sender {
    if (![self serviceReady]) {
        [self repairAction:sender];
        return;
    }
    if (!CPBool(self.statusSnapshot[@"codex_cli_found"])) {
        [self refreshSnapshots:sender];
        return;
    }
    if (![self hasUsableAccount]) {
        if ([self hasAnyAccount]) {
            self.activeSection = @"accounts";
            [self updateNavigationSelection];
            [self renderActiveSection];
            return;
        }
        [self startLoginAction:sender];
        return;
    }
    if (!CPBool(self.statusSnapshot[@"enabled"])) {
        [self enableProxyAction:sender];
        return;
    }
    if (![self proxyTrafficConfirmed]) {
        [self openCodexAction:sender];
        return;
    }
    [self refreshSnapshots:sender];
}

- (void)enableProxyAction:(id)sender {
    [self performAction:@[@"enable-codex-proxy"] label:@"启用 Codex 代理" refreshAfter:YES];
}

- (void)disableProxyAction:(id)sender {
    [self performAction:@[@"disable-codex-proxy"] label:@"Codex 直连" refreshAfter:YES];
}

- (void)showPathsAction:(id)sender {
    [self performAction:@[@"show-paths"] label:@"路径与依赖" refreshAfter:NO];
}

- (void)openCodexAction:(id)sender {
    if ([self showCodexMissingAlertIfNeededForCLI:NO openApp:YES]) {
        return;
    }
    [self performAction:@[@"repair-open-codex"] label:@"打开 Codex" refreshAfter:YES fromBundle:YES];
}

- (void)openWebAction:(id)sender {
    [self performAction:@[@"repair-open-web"] label:@"打开网页状态页" refreshAfter:YES fromBundle:YES];
}

- (void)tokenUsageModeAction:(NSControl *)sender {
    NSInteger mode = 0;
    if ([sender isKindOfClass:NSSegmentedControl.class]) {
        mode = ((NSSegmentedControl *)sender).selectedSegment;
    } else {
        mode = sender.tag;
    }
    self.tokenUsageMode = MAX(0, MIN(2, mode));
    if (self.window) {
        [self renderActiveSection];
    }
    if (self.settingsController.window) {
        [self.settingsController rebuildSettingsPagesSelectingIndex:self.settingsController.selectedSettingsIndex];
        [self.settingsController populateControls];
    }
}

- (void)scanAccountsAction:(id)sender {
    [self performAction:@[@"scan-accounts"] label:@"扫描账号" refreshAfter:YES];
}

- (void)clearRecentRequestsAction:(id)sender {
    [self setBusy:YES message:@"正在清空最近请求..."];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSDictionary *result = [self fetchJSONPath:@"/api/status/recent/clear" method:@"POST" timeout:5.0];
        dispatch_async(dispatch_get_main_queue(), ^{
            [self appendLog:[NSString stringWithFormat:@"清空最近请求\n%@", CPPrettyJSON(result ?: @{@"error": @"request failed"})]];
            [self setBusy:NO message:@"最近请求已清空"];
            [self refreshSnapshots:nil];
        });
    });
}

- (void)listAccountsAction:(id)sender {
    [self performAction:@[@"list-accounts"] label:@"列出账号" refreshAfter:YES];
}

- (void)openLogAction:(id)sender {
    [self performAction:@[@"open-log"] label:@"打开日志" refreshAfter:NO];
}

- (void)applyUpdateAction:(id)sender {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"应用更新";
    alert.informativeText = @"这会同步 App 内置运行资源，并重启代理一次。正在进行的 Codex 请求可能中断。继续吗？";
    [alert addButtonWithTitle:@"继续"];
    [alert addButtonWithTitle:@"取消"];
    if ([alert runModal] != NSAlertFirstButtonReturn) {
        return;
    }

    [self setBusy:YES message:@"正在执行：应用更新..."];
    [self appendLog:@"$ 应用更新"];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *error = nil;
        NSDictionary *result = nil;
        NSString *body = nil;
        NSString *raw = nil;
        result = [self runApplyUpdateJSONSyncRawText:&raw];
        if (!result) {
            result = @{@"error": raw ?: @"apply-update failed"};
        }
        body = CPPrettyJSON(result);
        [self writeResultWithTitle:@"应用更新" body:body];
        dispatch_async(dispatch_get_main_queue(), ^{
            [self appendLog:body];
            [self setBusy:NO message:@"应用更新已完成"];
            if (CPBool(result[@"frontend_restart_required"])) {
                NSString *version = CPDisplayString(result[@"expected_version"]);
                NSAlert *done = [[NSAlert alloc] init];
                done.messageText = @"后台已更新";
                done.informativeText = [NSString stringWithFormat:@"后台已更新到 %@，需要退出并重新打开小腊肠以显示新版界面。", version];
                [done addButtonWithTitle:@"知道了"];
                [done runModal];
            }
            [self refreshSnapshots:nil];
        });
    });
}

- (void)toggleAccountAction:(id)sender {
    NSString *name = [self selectedOrPromptedAccountNameWithTitle:@"启用/禁用账号" prompt:@"请输入账号名称："];
    if (name) {
        [self performAction:@[@"toggle-account", @"--name", name] label:[NSString stringWithFormat:@"启用/禁用账号 %@", name] refreshAfter:YES];
    }
}

- (void)deleteAccountAction:(id)sender {
    NSString *name = [self selectedOrPromptedAccountNameWithTitle:@"删除账号" prompt:@"请输入要删除的账号名称："];
    if (!name) {
        return;
    }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"删除账号";
    alert.informativeText = [NSString stringWithFormat:@"账号 %@ 会移到账号回收目录，不会直接抹除。继续吗？", name];
    [alert addButtonWithTitle:@"删除"];
    [alert addButtonWithTitle:@"取消"];
    if ([alert runModal] != NSAlertFirstButtonReturn) {
        return;
    }
    [self performAction:@[@"delete-account", @"--name", name] label:[NSString stringWithFormat:@"删除账号 %@", name] refreshAfter:YES];
}

- (void)refreshTokenAction:(id)sender {
    NSString *name = [self selectedOrPromptedAccountNameWithTitle:@"刷新账号令牌" prompt:@"请输入账号名称："];
    if (name) {
        [self performAction:@[@"refresh-token", @"--name", name] label:[NSString stringWithFormat:@"刷新令牌 %@", name] refreshAfter:YES];
    }
}

- (void)clearCooldownAction:(id)sender {
    NSString *name = [self selectedOrPromptedAccountNameWithTitle:@"解除账号冷却" prompt:@"请输入账号名称："];
    if (name) {
        [self performAction:@[@"clear-cooldown", @"--name", name] label:[NSString stringWithFormat:@"解除冷却 %@", name] refreshAfter:YES];
    }
}

- (void)clearAuthErrorAction:(id)sender {
    NSString *name = [self selectedOrPromptedAccountNameWithTitle:@"解除账号异常状态" prompt:@"请输入账号名称："];
    if (name) {
        [self performAction:@[@"clear-auth-error", @"--name", name] label:[NSString stringWithFormat:@"解除异常 %@", name] refreshAfter:YES];
    }
}

- (void)loginCommandAction:(id)sender {
    if ([self showCodexMissingAlertIfNeededForCLI:YES openApp:NO]) {
        return;
    }
    NSString *name = [self askAccountNameWithTitle:@"复制登录命令" prompt:@"请输入新账号名称："];
    if (name) {
        [self performAction:@[@"login-command", @"--name", name] label:[NSString stringWithFormat:@"复制登录命令 %@", name] refreshAfter:YES];
    }
}

- (void)startLoginAction:(id)sender {
    if ([self showCodexMissingAlertIfNeededForCLI:YES openApp:NO]) {
        return;
    }
    NSString *name = [self askAccountNameWithTitle:@"打开登录页" prompt:@"请输入新账号名称："];
    if (!name) {
        return;
    }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"打开登录页";
    alert.informativeText = @"App 会启动 codex login，并在浏览器打开 OpenAI 登录页。登录完成后回到 App 点击“扫描账号”。";
    [alert addButtonWithTitle:@"打开"];
    [alert addButtonWithTitle:@"取消"];
    if ([alert runModal] != NSAlertFirstButtonReturn) {
        return;
    }
    [self performAction:@[@"start-login", @"--name", name] label:[NSString stringWithFormat:@"打开登录页 %@", name] refreshAfter:YES];
}

- (void)importCurrentAction:(id)sender {
    NSString *name = [self askAccountNameWithTitle:@"导入当前账号" prompt:@"保存为哪个账号名称？"];
    if (name) {
        [self performAction:@[@"import-current", @"--name", name] label:[NSString stringWithFormat:@"导入当前账号 %@", name] refreshAfter:YES];
    }
}

- (void)openResultAction:(id)sender {
    [NSWorkspace.sharedWorkspace openURL:[NSURL fileURLWithPath:self.resultPath]];
}

#pragma mark - Runtime / Python

- (NSArray<NSString *> *)runtimePythonCandidates {
    return @[
        [[self.runtimeDir stringByAppendingPathComponent:@"python/bin"] stringByAppendingPathComponent:@"python3"],
        [[self.runtimeDir stringByAppendingPathComponent:@"python/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS"] stringByAppendingPathComponent:@"Python"],
    ];
}

- (NSArray<NSString *> *)resourcePythonCandidates {
    return @[
        [[self.resourceRuntimeDir stringByAppendingPathComponent:@"python/bin"] stringByAppendingPathComponent:@"python3"],
        [[self.resourceRuntimeDir stringByAppendingPathComponent:@"python/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS"] stringByAppendingPathComponent:@"Python"],
    ];
}

- (NSString *)pythonExecutablePreferRuntime:(BOOL)preferRuntime {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSMutableArray<NSString *> *candidates = [NSMutableArray array];
    if (preferRuntime) {
        [candidates addObjectsFromArray:[self runtimePythonCandidates]];
        [candidates addObjectsFromArray:[self resourcePythonCandidates]];
    } else {
        [candidates addObjectsFromArray:[self resourcePythonCandidates]];
        [candidates addObjectsFromArray:[self runtimePythonCandidates]];
    }
    [candidates addObjectsFromArray:@[
        @"/usr/bin/python3",
        @"/Library/Developer/CommandLineTools/usr/bin/python3",
    ]];
    for (NSString *candidate in candidates) {
        if ([fm isExecutableFileAtPath:candidate]) {
            return candidate;
        }
    }
    return @"/usr/bin/python3";
}

- (NSString *)pythonExecutable {
    return [self pythonExecutablePreferRuntime:YES];
}

- (NSString *)runtimeVendorPath {
    NSString *vendor = [self.runtimeDir stringByAppendingPathComponent:@"vendor"];
    if ([NSFileManager.defaultManager fileExistsAtPath:vendor]) {
        return vendor;
    }
    return @"";
}

- (NSString *)vendorPathForSourceDir:(NSString *)sourceDir fallbackToRuntime:(BOOL)fallbackToRuntime {
    NSString *sourceVendor = [sourceDir stringByAppendingPathComponent:@"vendor"];
    BOOL isDir = NO;
    if ([NSFileManager.defaultManager fileExistsAtPath:sourceVendor isDirectory:&isDir] && isDir) {
        return sourceVendor;
    }
    return fallbackToRuntime ? [self runtimeVendorPath] : @"";
}

- (BOOL)ensureRuntimeReady:(NSError **)error {
    NSFileManager *fm = NSFileManager.defaultManager;
    BOOL isDir = NO;
    if (![fm fileExistsAtPath:self.resourceRuntimeDir isDirectory:&isDir] || !isDir) {
        if (error) {
            *error = [NSError errorWithDomain:@"CodexProxyControl"
                                         code:1
                                     userInfo:@{NSLocalizedDescriptionKey: @"App 内缺少 Contents/Resources/runtime"}];
        }
        return NO;
    }
    [self migrateLegacyRuntimeIfNeeded];
    return [self copyRuntimeResourcesForce:NO error:error];
}

- (void)migrateLegacyRuntimeIfNeeded {
    NSString *legacy = [@"~/Library/Application Support/codexproxyapi" stringByExpandingTildeInPath];
    NSFileManager *fm = NSFileManager.defaultManager;
    BOOL isDir = NO;
    if ([fm fileExistsAtPath:self.runtimeDir isDirectory:&isDir]) {
        return;
    }
    if (![fm fileExistsAtPath:legacy isDirectory:&isDir] || !isDir) {
        return;
    }
    NSError *error = nil;
    if ([fm copyItemAtPath:legacy toPath:self.runtimeDir error:&error]) {
        [self appendLog:@"已从旧运行目录迁移账号、配置和统计数据。"];
    } else {
        [self appendLog:[NSString stringWithFormat:@"旧运行目录迁移失败：%@", error.localizedDescription]];
    }
}

- (BOOL)copyRuntimeResourcesForce:(BOOL)force error:(NSError **)error {
    NSFileManager *fm = NSFileManager.defaultManager;
    if (![fm createDirectoryAtPath:self.runtimeDir withIntermediateDirectories:YES attributes:nil error:error]) {
        return NO;
    }

    NSArray<NSString *> *items = [fm contentsOfDirectoryAtPath:self.resourceRuntimeDir error:error];
    if (!items) {
        return NO;
    }

    for (NSString *item in items) {
        if ([item isEqualToString:@"accounts"]) {
            continue;
        }
        NSString *src = [self.resourceRuntimeDir stringByAppendingPathComponent:item];
        NSString *dst = [self.runtimeDir stringByAppendingPathComponent:item];
        BOOL dstExists = [fm fileExistsAtPath:dst];
        if ([item isEqualToString:@"config.json"] && dstExists) {
            continue;
        }
        if (dstExists && ![fm removeItemAtPath:dst error:error]) {
            return NO;
        }
        if (![fm copyItemAtPath:src toPath:dst error:error]) {
            return NO;
        }
    }
    return YES;
}

- (NSDictionary<NSString *, NSString *> *)taskEnvironmentForSourceDir:(NSString *)sourceDir
                                                      includeProxyPython:(BOOL)includeProxyPython
                                                     fallbackToRuntime:(BOOL)fallbackToRuntime {
    NSMutableDictionary *env = [NSProcessInfo.processInfo.environment mutableCopy];
    env[@"CODEX_PROXY_SOURCE_DIR"] = sourceDir;
    env[@"CODEX_PROXY_APP_BUNDLE"] = self.appBundlePath;
    if (includeProxyPython) {
        env[@"CODEX_PROXY_PYTHON"] = [self pythonExecutable];
    } else {
        [env removeObjectForKey:@"CODEX_PROXY_PYTHON"];
    }
    NSString *vendor = [self vendorPathForSourceDir:sourceDir fallbackToRuntime:fallbackToRuntime];
    if (vendor.length > 0) {
        NSString *oldPath = env[@"PYTHONPATH"];
        env[@"PYTHONPATH"] = oldPath.length > 0 ? [NSString stringWithFormat:@"%@:%@", vendor, oldPath] : vendor;
    }
    return env;
}

- (NSDictionary<NSString *, NSString *> *)taskEnvironment {
    return [self taskEnvironmentForSourceDir:self.resourceRuntimeDir includeProxyPython:YES fallbackToRuntime:YES];
}

- (NSString *)runPythonTextSyncWithScript:(NSString *)script
                         workingDirectory:(NSString *)workingDirectory
                               executable:(NSString *)executable
                                     args:(NSArray<NSString *> *)args
                              environment:(NSDictionary<NSString *, NSString *> *)environment
                                 exitCode:(int *)exitCode {
    if (![NSFileManager.defaultManager fileExistsAtPath:script]) {
        if (exitCode) {
            *exitCode = 127;
        }
        return [NSString stringWithFormat:@"运行目录缺少控制脚本：%@\n请点击“应用更新”同步运行目录。", script];
    }

    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:executable];
    task.currentDirectoryURL = [NSURL fileURLWithPath:workingDirectory];
    NSMutableArray<NSString *> *arguments = [NSMutableArray arrayWithObjects:@"-B", script, nil];
    [arguments addObjectsFromArray:args];
    task.arguments = arguments;
    task.environment = environment;

    NSPipe *pipe = [NSPipe pipe];
    task.standardOutput = pipe;
    task.standardError = pipe;

    @try {
        NSError *error = nil;
        if (![task launchAndReturnError:&error]) {
            if (exitCode) {
                *exitCode = 1;
            }
            return [NSString stringWithFormat:@"执行操作失败：%@", error.localizedDescription];
        }
        [task waitUntilExit];
    } @catch (NSException *exception) {
        if (exitCode) {
            *exitCode = 1;
        }
        return [NSString stringWithFormat:@"执行操作失败：%@", exception.reason];
    }

    NSData *data = [pipe.fileHandleForReading readDataToEndOfFile];
    NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: @"";
    if (exitCode) {
        *exitCode = task.terminationStatus;
    }
    return text.length > 0 ? text : @"{}";
}

- (NSString *)runPythonTextSync:(NSArray<NSString *> *)args exitCode:(int *)exitCode {
    NSString *script = [self.runtimeDir stringByAppendingPathComponent:@"control_actions.py"];
    return [self runPythonTextSyncWithScript:script
                            workingDirectory:self.runtimeDir
                                  executable:[self pythonExecutable]
                                        args:args
                                 environment:[self taskEnvironment]
                                    exitCode:exitCode];
}

- (NSDictionary *)runPythonJSONSyncWithScript:(NSString *)script
                             workingDirectory:(NSString *)workingDirectory
                                   executable:(NSString *)executable
                                         args:(NSArray<NSString *> *)args
                                  environment:(NSDictionary<NSString *, NSString *> *)environment
                                      rawText:(NSString **)rawText {
    NSMutableArray *arguments = [args mutableCopy];
    [arguments addObjectsFromArray:@[@"--format", @"json"]];
    int exitCode = 0;
    NSString *text = [self runPythonTextSyncWithScript:script
                                      workingDirectory:workingDirectory
                                            executable:executable
                                                  args:arguments
                                           environment:environment
                                              exitCode:&exitCode];
    if (rawText) {
        *rawText = text;
    }
    NSData *data = [text dataUsingEncoding:NSUTF8StringEncoding];
    id parsed = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if ([parsed isKindOfClass:NSDictionary.class]) {
        if (exitCode == 0) {
            return parsed;
        }
        NSMutableDictionary *failed = [parsed mutableCopy];
        failed[@"exit_code"] = @(exitCode);
        return failed;
    }
    return @{@"error": text ?: @"request failed", @"exit_code": @(exitCode)};
}

- (NSDictionary *)runPythonJSONSync:(NSArray<NSString *> *)args rawText:(NSString **)rawText {
    NSString *script = [self.runtimeDir stringByAppendingPathComponent:@"control_actions.py"];
    return [self runPythonJSONSyncWithScript:script
                            workingDirectory:self.runtimeDir
                                  executable:[self pythonExecutable]
                                        args:args
                                 environment:[self taskEnvironment]
                                     rawText:rawText];
}

- (NSDictionary *)runApplyUpdateJSONSyncRawText:(NSString **)rawText {
    return [self runBundleActionJSONSync:@[@"apply-update"] rawText:rawText];
}

// Run a control action from the pristine App bundle copy (not the runtime copy).
// The runtime copy started life as a clone of the old 0.5.4 runtime, so running
// repair/install logic from there can execute stale code that fails to fully
// retire the legacy service. The bundle copy is always the newest logic.
- (NSDictionary *)runBundleActionJSONSync:(NSArray<NSString *> *)args rawText:(NSString **)rawText {
    NSString *script = [self.resourceRuntimeDir stringByAppendingPathComponent:@"control_actions.py"];
    NSDictionary *environment = [self taskEnvironmentForSourceDir:self.resourceRuntimeDir
                                               includeProxyPython:NO
                                                fallbackToRuntime:NO];
    return [self runPythonJSONSyncWithScript:script
                            workingDirectory:self.resourceRuntimeDir
                                  executable:[self pythonExecutablePreferRuntime:NO]
                                        args:args
                                 environment:environment
                                     rawText:rawText];
}

- (id)fetchJSONPath:(NSString *)path method:(NSString *)method timeout:(NSTimeInterval)timeout {
    NSString *urlString = [@"http://127.0.0.1:8800" stringByAppendingString:path];
    NSURL *url = [NSURL URLWithString:urlString];
    if (!url) {
        return nil;
    }
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:timeout];
    request.HTTPMethod = method ?: @"GET";
    if (![request.HTTPMethod isEqualToString:@"GET"]) {
        request.HTTPBody = [NSData data];
    }

    dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
    __block NSData *responseData = nil;
    NSURLSessionDataTask *task = [NSURLSession.sharedSession dataTaskWithRequest:request
                                                               completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSHTTPURLResponse *http = [response isKindOfClass:NSHTTPURLResponse.class] ? (NSHTTPURLResponse *)response : nil;
        if (!error && http.statusCode >= 200 && http.statusCode < 300) {
            responseData = data;
        }
        dispatch_semaphore_signal(semaphore);
    }];
    [task resume];
    dispatch_semaphore_wait(semaphore, dispatch_time(DISPATCH_TIME_NOW, (int64_t)((timeout + 1.0) * NSEC_PER_SEC)));
    if (!responseData) {
        [task cancel];
        return nil;
    }
    return [NSJSONSerialization JSONObjectWithData:responseData options:0 error:nil];
}

- (void)writeResultWithTitle:(NSString *)title body:(NSString *)body {
    NSString *content = [NSString stringWithFormat:@"小腊肠\n操作：%@\n时间：%@\n\n%@\n\n日志：%@\n",
                         title,
                         NSDate.date,
                         body ?: @"",
                         self.logPath];
    [NSFileManager.defaultManager createDirectoryAtPath:self.runtimeDir
                            withIntermediateDirectories:YES
                                             attributes:nil
                                                  error:nil];
    [content writeToFile:self.resultPath atomically:YES encoding:NSUTF8StringEncoding error:nil];
}

#pragma mark - State / Tables

- (void)setBusy:(BOOL)busy message:(NSString *)message {
    self.busy = busy;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.footerStatusLabel) {
            self.footerStatusLabel.stringValue = message ?: @"";
        }
        for (NSButton *button in self.buttons) {
            if (button.window) {
                button.enabled = !busy;
            }
        }
        for (NSButton *button in self.navButtons) {
            button.enabled = !busy;
        }
    });
}

- (void)appendLog:(NSString *)text {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!self.outputView) {
            return;
        }
        NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
        formatter.dateFormat = @"HH:mm:ss";
        NSString *stamp = [formatter stringFromDate:NSDate.date];
        NSString *line = [NSString stringWithFormat:@"[%@] %@\n", stamp, text ?: @""];
        NSString *old = self.outputView.string ?: @"";
        self.outputView.string = [old stringByAppendingString:line];
        [self.outputView scrollToEndOfDocument:nil];
    });
}

- (void)auditVisibleButtonsWithContext:(NSString *)context {
    NSMutableArray<NSButton *> *buttons = [NSMutableArray array];
    [self collectButtonsFromView:self.window.contentView into:buttons];
    NSMutableArray<NSString *> *issues = [NSMutableArray array];
    for (NSInteger i = 0; i < (NSInteger)buttons.count; i++) {
        NSButton *a = buttons[i];
        if (a.hidden || a.alphaValue <= 0.01 || !a.window) {
            continue;
        }
        NSRect af = [a.superview convertRect:a.frame toView:nil];
        CGFloat needed = a.intrinsicContentSize.width;
        if (needed > 0 && af.size.width > 0 && needed > af.size.width + 3) {
            [issues addObject:[NSString stringWithFormat:@"裁切：%@ need %.0f > %.0f", a.title, needed, af.size.width]];
        }
        for (NSInteger j = i + 1; j < (NSInteger)buttons.count; j++) {
            NSButton *b = buttons[j];
            if (b.hidden || b.alphaValue <= 0.01 || !b.window) {
                continue;
            }
            NSRect bf = [b.superview convertRect:b.frame toView:nil];
            NSRect inter = NSIntersectionRect(af, bf);
            if (!NSIsEmptyRect(inter) && inter.size.width * inter.size.height > 4) {
                [issues addObject:[NSString stringWithFormat:@"重叠：%@ / %@", a.title, b.title]];
            }
        }
    }
    if (issues.count) {
        [self appendLog:[NSString stringWithFormat:@"布局巡检 %@\n%@", context, [issues componentsJoinedByString:@"\n"]]];
    }
}

- (void)collectButtonsFromView:(NSView *)view into:(NSMutableArray<NSButton *> *)buttons {
    if (view.hidden || view.alphaValue <= 0.01) {
        return;
    }
    if ([view isKindOfClass:NSButton.class]) {
        [buttons addObject:(NSButton *)view];
    }
    for (NSView *subview in view.subviews) {
        [self collectButtonsFromView:subview into:buttons];
    }
}

- (NSInteger)numberOfRowsInTableView:(NSTableView *)tableView {
    return self.accounts.count;
}

- (NSView *)tableView:(NSTableView *)tableView viewForTableColumn:(NSTableColumn *)tableColumn row:(NSInteger)row {
    NSDictionary *account = row >= 0 && row < self.accounts.count ? self.accounts[row] : @{};
    NSString *identifier = tableColumn.identifier;
    NSTableCellView *cell = [tableView makeViewWithIdentifier:identifier owner:self];
    if (!cell) {
        cell = [[NSTableCellView alloc] init];
        cell.identifier = identifier;
        NSTextField *field = [NSTextField labelWithString:@""];
        field.translatesAutoresizingMaskIntoConstraints = NO;
        field.lineBreakMode = NSLineBreakByTruncatingMiddle;
        field.font = [NSFont systemFontOfSize:11 weight:NSFontWeightRegular];
        cell.textField = field;
        [cell addSubview:field];
        [NSLayoutConstraint activateConstraints:@[
            [field.leadingAnchor constraintEqualToAnchor:cell.leadingAnchor constant:2],
            [field.trailingAnchor constraintEqualToAnchor:cell.trailingAnchor constant:-2],
            [field.centerYAnchor constraintEqualToAnchor:cell.centerYAnchor],
        ]];
    }

    cell.textField.textColor = NSColor.labelColor;
    BOOL leftAligned = [identifier isEqualToString:@"name"] || [identifier isEqualToString:@"email"];
    cell.textField.alignment = leftAligned ? NSTextAlignmentLeft : NSTextAlignmentCenter;
    cell.textField.lineBreakMode = [identifier isEqualToString:@"email"] ? NSLineBreakByTruncatingMiddle : NSLineBreakByTruncatingTail;
    if ([identifier isEqualToString:@"name"]) {
        cell.textField.font = [NSFont systemFontOfSize:11 weight:NSFontWeightSemibold];
        cell.textField.stringValue = CPDisplayString(account[@"name"]);
    } else if ([identifier isEqualToString:@"email"]) {
        cell.textField.stringValue = CPDisplayString(account[@"email"]);
    } else if ([identifier isEqualToString:@"state"]) {
        cell.textField.stringValue = [self stateLabelForAccount:account];
        cell.textField.textColor = [self stateColorForAccount:account];
    } else if ([identifier isEqualToString:@"quota"]) {
        cell.textField.stringValue = [self quotaTextForAccountName:CPString(account[@"name"]) weekly:NO];
    } else if ([identifier isEqualToString:@"weekly"]) {
        cell.textField.stringValue = [self quotaTextForAccountName:CPString(account[@"name"]) weekly:YES];
    } else if ([identifier isEqualToString:@"expires"]) {
        cell.textField.stringValue = CPRelativeTime(account[@"expires_at"]);
    } else if ([identifier isEqualToString:@"account_id"]) {
        cell.textField.stringValue = CPDisplayString(account[@"account_id"]);
    } else {
        cell.textField.stringValue = @"-";
    }
    return cell;
}

- (void)tableViewSelectionDidChange:(NSNotification *)notification {
    NSInteger row = self.accountTable.selectedRow;
    if (row >= 0 && row < self.accounts.count) {
        self.selectedAccountName = CPString(self.accounts[row][@"name"]);
        [self rebuildInspector];
    }
}

- (void)reloadAccountTableSelection {
    [self.accountTable reloadData];
    if (!self.accountTable || !self.selectedAccountName.length) {
        return;
    }
    NSInteger selected = -1;
    for (NSInteger index = 0; index < self.accounts.count; index++) {
        if ([CPString(self.accounts[index][@"name"]) isEqualToString:self.selectedAccountName]) {
            selected = index;
            break;
        }
    }
    if (selected < 0 && self.accounts.count) {
        selected = 0;
        self.selectedAccountName = CPString(self.accounts[0][@"name"]);
    }
    if (selected >= 0) {
        [self.accountTable selectRowIndexes:[NSIndexSet indexSetWithIndex:selected] byExtendingSelection:NO];
    }
    [self rebuildInspector];
}

- (NSDictionary *)selectedAccount {
    for (NSDictionary *account in self.accounts) {
        if ([CPString(account[@"name"]) isEqualToString:self.selectedAccountName]) {
            return account;
        }
    }
    return self.accounts.count ? self.accounts.firstObject : @{};
}

- (NSView *)accountGlobalActionsRow {
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 6;

    NSTextField *title = [self labelWithText:@"账号操作"
                                        font:[NSFont systemFontOfSize:15 weight:NSFontWeightBold]
                                       color:NSColor.labelColor];
    [stack addArrangedSubview:title];

    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.spacing = 6;
    row.distribution = NSStackViewDistributionFillEqually;
    [row addArrangedSubview:[self smallButtonWithTitle:@"登录" symbol:@"plus" selector:@selector(startLoginAction:)]];
    [row addArrangedSubview:[self smallButtonWithTitle:@"导入" symbol:@"square.and.arrow.down" selector:@selector(importCurrentAction:)]];
    [row addArrangedSubview:[self smallButtonWithTitle:@"复制命令" symbol:@"doc.on.doc" selector:@selector(loginCommandAction:)]];
    [stack addArrangedSubview:row];
    return stack;
}

- (void)rebuildInspector {
    if (!self.inspectorStack) {
        return;
    }
    NSArray *oldViews = self.inspectorStack.arrangedSubviews.copy;
    for (NSView *view in oldViews) {
        [self.inspectorStack removeArrangedSubview:view];
        [view removeFromSuperview];
    }

    if (!self.compactInspector) {
        [self.inspectorStack addArrangedSubview:[self accountGlobalActionsRow]];
    }

    NSDictionary *account = [self selectedAccount];
    if (!account.count) {
        [self.inspectorStack addArrangedSubview:[self labelWithText:self.compactInspector ? @"选中账号" : @"账号检查器" font:[NSFont systemFontOfSize:self.compactInspector ? 15 : 17 weight:NSFontWeightBold] color:NSColor.labelColor]];
        [self.inspectorStack addArrangedSubview:[self emptyStateLabel:@"没有可管理账号。请添加账号或扫描账号目录。"]];
        return;
    }

    NSString *name = CPDisplayString(account[@"name"]);
    if (self.compactInspector) {
        NSStackView *header = [[NSStackView alloc] init];
        header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        header.alignment = NSLayoutAttributeCenterY;
        header.spacing = 8;
        [header addArrangedSubview:[self labelWithText:@"选中账号" font:[NSFont systemFontOfSize:15 weight:NSFontWeightBold] color:NSColor.labelColor]];
        [self.inspectorStack addArrangedSubview:header];

        NSString *summary = [NSString stringWithFormat:@"%@ · %@",
                             name,
                             [self stateLabelForAccount:account]];
        NSTextField *summaryLabel = [self labelWithText:summary font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
        summaryLabel.lineBreakMode = NSLineBreakByTruncatingMiddle;
        [self.inspectorStack addArrangedSubview:summaryLabel];
        NSTextField *reasonLabel = [self labelWithText:[self selectionReasonForAccountName:CPString(account[@"name"])] font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
        reasonLabel.lineBreakMode = NSLineBreakByTruncatingTail;
        [self.inspectorStack addArrangedSubview:reasonLabel];
        [self.inspectorStack addArrangedSubview:[self accountInspectorInfoRowWithTitle:@"邮箱" value:CPDisplayString(account[@"email"])]];
        [self.inspectorStack addArrangedSubview:[self accountInspectorInfoRowWithTitle:@"Token" value:CPRelativeTime(account[@"expires_at"])]];
        [self.inspectorStack addArrangedSubview:[self accountInspectorInfoRowWithTitle:@"5h 剩余" value:[self quotaTextForAccountName:CPString(account[@"name"]) weekly:NO]]];
        [self.inspectorStack addArrangedSubview:[self accountInspectorInfoRowWithTitle:@"5h 刷新" value:[self quotaResetTextForAccountName:CPString(account[@"name"]) weekly:NO]]];
        [self.inspectorStack addArrangedSubview:[self accountInspectorInfoRowWithTitle:@"7d 剩余" value:[self quotaTextForAccountName:CPString(account[@"name"]) weekly:YES]]];
        [self.inspectorStack addArrangedSubview:[self accountInspectorInfoRowWithTitle:@"7d 刷新" value:[self quotaResetTextForAccountName:CPString(account[@"name"]) weekly:YES]]];

        NSStackView *buttonGrid = [[NSStackView alloc] init];
        buttonGrid.orientation = NSUserInterfaceLayoutOrientationVertical;
        buttonGrid.alignment = NSLayoutAttributeWidth;
        buttonGrid.spacing = 8;
        buttonGrid.translatesAutoresizingMaskIntoConstraints = NO;
        NSStackView *top = [[NSStackView alloc] init];
        top.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        top.alignment = NSLayoutAttributeCenterY;
        top.spacing = 8;
        top.distribution = NSStackViewDistributionFillEqually;
        [top.heightAnchor constraintEqualToConstant:30].active = YES;
        [top addArrangedSubview:[self smallButtonWithTitle:@"刷新令牌" symbol:@"key" selector:@selector(refreshTokenAction:)]];
        [top addArrangedSubview:[self smallButtonWithTitle:CPBool(account[@"enabled"]) ? @"禁用" : @"启用" symbol:@"power" selector:@selector(toggleAccountAction:)]];
        NSStackView *bottom = [[NSStackView alloc] init];
        bottom.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        bottom.alignment = NSLayoutAttributeCenterY;
        bottom.spacing = 8;
        bottom.distribution = NSStackViewDistributionFillEqually;
        [bottom.heightAnchor constraintEqualToConstant:30].active = YES;
        [bottom addArrangedSubview:[self smallButtonWithTitle:@"解除冷却" symbol:@"timer" selector:@selector(clearCooldownAction:)]];
        [bottom addArrangedSubview:[self smallButtonWithTitle:@"解除异常" symbol:@"exclamationmark.triangle" selector:@selector(clearAuthErrorAction:)]];
        NSStackView *danger = [[NSStackView alloc] init];
        danger.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        danger.alignment = NSLayoutAttributeCenterY;
        danger.spacing = 8;
        [danger.heightAnchor constraintEqualToConstant:30].active = YES;
        NSButton *deleteButton = [self smallButtonWithTitle:@"删除" symbol:@"trash" selector:@selector(deleteAccountAction:)];
        [danger addArrangedSubview:deleteButton];
        [buttonGrid addArrangedSubview:top];
        [buttonGrid addArrangedSubview:bottom];
        [buttonGrid addArrangedSubview:danger];
        [self.inspectorStack addArrangedSubview:buttonGrid];
        [buttonGrid.widthAnchor constraintEqualToAnchor:self.inspectorStack.widthAnchor].active = YES;
        [top.widthAnchor constraintEqualToAnchor:buttonGrid.widthAnchor].active = YES;
        [bottom.widthAnchor constraintEqualToAnchor:buttonGrid.widthAnchor].active = YES;
        [danger.widthAnchor constraintEqualToAnchor:buttonGrid.widthAnchor].active = YES;
        [deleteButton.widthAnchor constraintEqualToAnchor:danger.widthAnchor].active = YES;
        return;
    }

    [self.inspectorStack addArrangedSubview:[self labelWithText:@"账号检查器" font:[NSFont systemFontOfSize:17 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSStackView *stateRow = [[NSStackView alloc] init];
    stateRow.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    stateRow.spacing = 8;
    stateRow.alignment = NSLayoutAttributeCenterY;
    [stateRow addArrangedSubview:[self statusDotWithColor:[self stateColorForAccount:account]]];
    [stateRow addArrangedSubview:[self labelWithText:[self stateLabelForAccount:account] font:[NSFont systemFontOfSize:13 weight:NSFontWeightMedium] color:[self stateColorForAccount:account]]];
    [self.inspectorStack addArrangedSubview:stateRow];
    [self.inspectorStack addArrangedSubview:[self labelWithText:name font:[NSFont systemFontOfSize:26 weight:NSFontWeightBold] color:NSColor.labelColor]];
    [self.inspectorStack addArrangedSubview:[self labelWithText:CPDisplayString(account[@"email"]) font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor]];

    [self.inspectorStack addArrangedSubview:[self infoRowWithTitle:@"Token" value:CPRelativeTime(account[@"expires_at"])]];
    [self.inspectorStack addArrangedSubview:[self infoRowWithTitle:@"选择原因" value:[self selectionReasonForAccountName:CPString(account[@"name"])]]];
    [self.inspectorStack addArrangedSubview:[self infoRowWithTitle:@"5h 剩余" value:[self quotaTextForAccountName:CPString(account[@"name"]) weekly:NO]]];
    [self.inspectorStack addArrangedSubview:[self infoRowWithTitle:@"7d 剩余" value:[self quotaTextForAccountName:CPString(account[@"name"]) weekly:YES]]];
    [self.inspectorStack addArrangedSubview:[self infoRowWithTitle:@"Account ID" value:CPDisplayString(account[@"account_id"])]];

    NSStackView *buttonGrid = [[NSStackView alloc] init];
    buttonGrid.orientation = NSUserInterfaceLayoutOrientationVertical;
    buttonGrid.spacing = 8;
    NSStackView *top = [[NSStackView alloc] init];
    top.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    top.spacing = 8;
    [top addArrangedSubview:[self smallButtonWithTitle:@"刷新令牌" symbol:@"key" selector:@selector(refreshTokenAction:)]];
    [top addArrangedSubview:[self smallButtonWithTitle:CPBool(account[@"enabled"]) ? @"禁用" : @"启用" symbol:@"power" selector:@selector(toggleAccountAction:)]];
    [buttonGrid addArrangedSubview:top];
    NSStackView *bottom = [[NSStackView alloc] init];
    bottom.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    bottom.spacing = 8;
    [bottom addArrangedSubview:[self smallButtonWithTitle:@"解除冷却" symbol:@"timer" selector:@selector(clearCooldownAction:)]];
    [bottom addArrangedSubview:[self smallButtonWithTitle:@"解除异常" symbol:@"exclamationmark.triangle" selector:@selector(clearAuthErrorAction:)]];
    [buttonGrid addArrangedSubview:bottom];
    [buttonGrid addArrangedSubview:[self actionButtonWithTitle:@"删除账号" symbol:@"trash" selector:@selector(deleteAccountAction:) primary:NO]];
    [self.inspectorStack addArrangedSubview:buttonGrid];
}

- (NSString *)stateLabelForAccount:(NSDictionary *)account {
    if (CPString(account[@"auth_error"]).length) {
        return @"认证异常";
    }
    if (!CPBool(account[@"has_tokens"])) {
        return @"缺令牌";
    }
    if (!CPBool(account[@"enabled"])) {
        return @"已禁用";
    }
    if (CPBool(account[@"rate_limited"])) {
        return CPString(account[@"cooldown_reason"]).length ? CPString(account[@"cooldown_reason"]) : @"冷却中";
    }
    return @"可用";
}

- (NSColor *)stateColorForAccount:(NSDictionary *)account {
    if (CPString(account[@"auth_error"]).length || !CPBool(account[@"has_tokens"])) {
        return NSColor.systemRedColor;
    }
    if (!CPBool(account[@"enabled"]) || CPBool(account[@"rate_limited"])) {
        return NSColor.systemOrangeColor;
    }
    return NSColor.systemGreenColor;
}

- (double)quotaRemainingForAccountName:(NSString *)name weekly:(BOOL)weekly {
    NSDictionary *quota = CPDict(self.quotaSnapshot[name]);
    NSDictionary *rateLimit = CPDict(quota[@"rate_limit"]);
    NSDictionary *window = CPDict(rateLimit[weekly ? @"secondary_window" : @"primary_window"]);
    id used = window[@"used_percent"];
    if (!used || used == NSNull.null) {
        used = weekly ? quota[@"weekly_usage"] : quota[@"5h_usage"];
    }
    if (!used || used == NSNull.null) {
        return 0;
    }
    return MAX(0, MIN(100, 100 - CPDouble(used)));
}

- (NSString *)quotaTextForAccountName:(NSString *)name weekly:(BOOL)weekly {
    NSDictionary *quota = CPDict(self.quotaSnapshot[name]);
    if (!quota.count || quota == (id)NSNull.null || quota[@"error"]) {
        return @"无数据";
    }
    double remaining = [self quotaRemainingForAccountName:name weekly:weekly];
    return [NSString stringWithFormat:@"%.0f%%", remaining];
}

- (NSString *)quotaFetchedTextForAccountName:(NSString *)name {
    NSDictionary *quota = CPDict(self.quotaSnapshot[name]);
    NSTimeInterval fetchedAt = CPDouble(quota[@"_fetched_at"]);
    if (fetchedAt <= 0) {
        return @"未刷新";
    }
    return [NSString stringWithFormat:@"刷新 %@", CPFullDateTime(@(fetchedAt))];
}

- (NSString *)quotaResetTextForAccountName:(NSString *)name weekly:(BOOL)weekly {
    NSString *prefix = weekly ? @"7d" : @"5h";
    NSDictionary *quota = CPDict(self.quotaSnapshot[name]);
    NSDictionary *rateLimit = CPDict(quota[@"rate_limit"]);
    NSDictionary *window = CPDict(rateLimit[weekly ? @"secondary_window" : @"primary_window"]);
    NSTimeInterval resetAt = CPDouble(window[@"reset_at"]);
    if (resetAt <= 0) {
        NSTimeInterval fetchedAt = CPDouble(quota[@"_fetched_at"]);
        NSTimeInterval resetAfter = CPDouble(window[@"reset_after_seconds"]);
        if (fetchedAt > 0 && resetAfter > 0) {
            resetAt = fetchedAt + resetAfter;
        }
    }
    if (resetAt <= 0) {
        return [NSString stringWithFormat:@"%@未刷新", prefix];
    }
    return [NSString stringWithFormat:@"%@刷新 %@", prefix, CPFullDateTime(@(resetAt))];
}

- (NSString *)requestTimeText:(id)value {
    NSTimeInterval epoch = CPDouble(value);
    if (epoch <= 0) {
        return @"-";
    }
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.dateFormat = @"HH:mm:ss";
    return [formatter stringFromDate:[NSDate dateWithTimeIntervalSince1970:epoch]] ?: @"-";
}

- (NSString *)selectedOrPromptedAccountNameWithTitle:(NSString *)title prompt:(NSString *)prompt {
    if (self.selectedAccountName.length) {
        return self.selectedAccountName;
    }
    return [self askAccountNameWithTitle:title prompt:prompt];
}

- (NSString *)askAccountNameWithTitle:(NSString *)title prompt:(NSString *)prompt {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = title;
    alert.informativeText = prompt;
    [alert addButtonWithTitle:@"确定"];
    [alert addButtonWithTitle:@"取消"];
    NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 280, 26)];
    alert.accessoryView = field;
    NSModalResponse response = [alert runModal];
    if (response != NSAlertFirstButtonReturn) {
        return nil;
    }
    NSString *value = [field.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    return value.length > 0 ? value : nil;
}

#pragma mark - Navigation

- (void)navigationAction:(NSButton *)sender {
    NSArray *ids = @[@"overview", @"accounts", @"config", @"logs"];
    if (sender.tag >= 0 && sender.tag < ids.count) {
        self.activeSection = ids[sender.tag];
        [self updateNavigationSelection];
        [self renderActiveSection];
    }
}

- (void)updateNavigationSelection {
    NSArray *ids = @[@"overview", @"accounts", @"config", @"logs"];
    for (NSButton *button in self.navButtons) {
        BOOL selected = button.tag >= 0 && button.tag < ids.count && [ids[button.tag] isEqualToString:self.activeSection];
        button.state = selected ? NSControlStateValueOn : NSControlStateValueOff;
        button.layer.backgroundColor = selected ? [NSColor.controlAccentColor colorWithAlphaComponent:0.22].CGColor : NSColor.clearColor.CGColor;
        button.layer.borderWidth = selected ? 0.5 : 0;
        button.layer.borderColor = selected ? [NSColor.controlAccentColor colorWithAlphaComponent:0.30].CGColor : NSColor.clearColor.CGColor;
        button.contentTintColor = selected ? NSColor.controlAccentColor : NSColor.labelColor;
        NSUInteger index = [self.navButtons indexOfObject:button];
        NSColor *tint = selected ? NSColor.controlAccentColor : NSColor.labelColor;
        if (index != NSNotFound && index < self.navIconViews.count) {
            self.navIconViews[index].contentTintColor = tint;
        }
        if (index != NSNotFound && index < self.navTitleLabels.count) {
            self.navTitleLabels[index].textColor = tint;
        }
    }
}

@end

@implementation SettingsWindowController

- (instancetype)initWithOwner:(ControlWindowController *)owner {
    self = [super init];
    if (!self) {
        return nil;
    }
    _owner = owner;
    _controls = [NSMutableDictionary dictionary];
    _scrollViews = [NSMutableArray array];
    _settingsNavButtons = [NSMutableArray array];
    _settingsNavIconViews = [NSMutableArray array];
    _settingsNavTitleLabels = [NSMutableArray array];
    _configSnapshot = @{};
    _statusSnapshot = @{};
    _codexSnapshot = @{};
    _menubarLoginSnapshot = @{};
    _selectedSettingsIndex = 0;
    return self;
}

- (void)show {
    if (!self.window) {
        [self buildWindow];
    } else {
        self.window.delegate = self;
    }
    [self centerFixedWindowInVisibleScreen];
    [self seedInitialSnapshotsFromOwner];
    [self rebuildSettingsPagesSelectingIndex:self.selectedSettingsIndex];
    [self populateControls];
    [self renderSettingsSectionAtIndex:self.selectedSettingsIndex];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    [self refresh:nil];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self scrollAllTabsToTopAfterLayout];
    });
    [self auditButtonsInWindow:self.window context:@"settings"];
}

- (void)seedInitialSnapshotsFromOwner {
    NSDictionary *ownerStatus = CPDict(self.owner.statusSnapshot);
    self.statusSnapshot = ownerStatus;

    NSDictionary *config = CPDict(ownerStatus[@"config"]);
    self.configSnapshot = config.count ? config : [self defaultConfig];

    if (ownerStatus.count || !self.codexSnapshot.count) {
        self.codexSnapshot = @{
            @"enabled": ownerStatus[@"enabled"] ?: @(NO),
            @"mode": ownerStatus[@"mode"] ?: @"",
            @"expected": @{
                @"codex_base_url": ownerStatus[@"codex_expected_base_url"] ?: @"",
            },
        };
    }
}

- (void)centerFixedWindowInVisibleScreen {
    if (!self.window) {
        return;
    }
    NSScreen *screen = self.window.screen ?: NSScreen.mainScreen;
    NSRect visible = screen.visibleFrame;
    NSSize size = NSMakeSize(940, 620);
    NSRect frame = NSMakeRect(NSMidX(visible) - size.width / 2,
                              NSMidY(visible) - size.height / 2,
                              size.width,
                              size.height);
    [self.window setFrame:frame display:NO animate:NO];
    self.window.contentMinSize = size;
    self.window.contentMaxSize = size;
    self.window.minSize = size;
    self.window.maxSize = size;
}

- (void)buildWindow {
    self.controls = [NSMutableDictionary dictionary];
    self.scrollViews = [NSMutableArray array];
    self.statusLabel = nil;
    self.serviceLabel = nil;
    self.codexLabel = nil;
    self.baseURLLabel = nil;
    self.diagnosticsLabel = nil;
    self.summaryStatusLabel = nil;
    self.summaryAccountsLabel = nil;
    self.summaryVersionLabel = nil;
    self.overviewFocusServiceLabel = nil;
    self.overviewFocusAccountsLabel = nil;
    self.overviewFocusRepairLabel = nil;
    self.overviewFocusErrorsLabel = nil;
    self.overviewFocusQuotaLabel = nil;
    self.routingCurrentStrategyLabel = nil;
    self.routingCooldownLabel = nil;
    self.routingRefreshLabel = nil;
    self.routingWindowLabel = nil;
    self.codexModeSummaryLabel = nil;
    self.codexBaseSummaryLabel = nil;
    self.codexOpenAIBaseLabel = nil;
    self.codexChatGPTBaseLabel = nil;
    self.codexPortLabel = nil;
    self.codexRestartLabel = nil;
    self.advancedRestartImpactLabel = nil;
    self.advancedStreamImpactLabel = nil;
    self.advancedSessionImpactLabel = nil;
    self.advancedSaveImpactLabel = nil;
    self.runtimeDirLabel = nil;
    self.sourceDirLabel = nil;
    self.frontendVersionLabel = nil;
    self.runtimeVersionLabel = nil;
    self.proxyVersionLabel = nil;
    self.manifestLabel = nil;
    self.detailTitleLabel = nil;
    self.detailSubtitleLabel = nil;
    self.sidebarStatusLabel = nil;
    self.sidebarAccountsLabel = nil;
    self.sidebarVersionLabel = nil;
    self.proxyModeControl = nil;
    self.contentHost = nil;
    self.restoreDefaultsButton = nil;
    self.saveSettingsButton = nil;
    self.menuBarLoginItemControl = nil;
    self.menuBarLoginItemLabel = nil;
    self.settingsNavButtons = [NSMutableArray array];
    self.settingsNavIconViews = [NSMutableArray array];
    self.settingsNavTitleLabels = [NSMutableArray array];

    NSRect frame = NSMakeRect(0, 0, 940, 620);
    self.window = [[NSWindow alloc] initWithContentRect:frame
                                             styleMask:(NSWindowStyleMaskTitled |
                                                        NSWindowStyleMaskClosable |
                                                        NSWindowStyleMaskMiniaturizable |
                                                        NSWindowStyleMaskFullSizeContentView)
                                               backing:NSBackingStoreBuffered
                                                 defer:NO];
    self.window.title = @"控制中心";
    self.window.titleVisibility = NSWindowTitleHidden;
    self.window.titlebarAppearsTransparent = YES;
    self.window.opaque = YES;
    self.window.restorable = NO;
    self.window.contentMinSize = NSMakeSize(940, 620);
    self.window.contentMaxSize = NSMakeSize(940, 620);
    self.window.minSize = self.window.frame.size;
    self.window.maxSize = self.window.frame.size;
    [self.window standardWindowButton:NSWindowZoomButton].enabled = NO;
    self.window.backgroundColor = CPSettingsContentBackgroundColor();
    self.window.delegate = self;
    [self.window center];

    NSStackView *root = [[NSStackView alloc] init];
    root.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    root.alignment = NSLayoutAttributeHeight;
    root.spacing = 0;
    root.edgeInsets = NSEdgeInsetsMake(0, 0, 0, 0);
    root.translatesAutoresizingMaskIntoConstraints = NO;
    self.window.contentView = root;

    NSView *sidebar = [self settingsSidebarView];
    [root addArrangedSubview:sidebar];
    [sidebar.widthAnchor constraintEqualToConstant:188].active = YES;

    CPThemedView *detailPanel = [[CPThemedView alloc] init];
    detailPanel.wantsLayer = YES;
    detailPanel.cpBackgroundColor = CPSettingsContentBackgroundColor();
    detailPanel.cpBorderColor = NSColor.clearColor;
    detailPanel.layer.borderWidth = 0;
    detailPanel.layer.cornerRadius = 16;
    detailPanel.layer.masksToBounds = YES;
    if (@available(macOS 10.13, *)) {
        detailPanel.layer.maskedCorners = kCALayerMinXMinYCorner | kCALayerMinXMaxYCorner;
    }
    detailPanel.translatesAutoresizingMaskIntoConstraints = NO;
    [root addArrangedSubview:detailPanel];
    [detailPanel.widthAnchor constraintEqualToConstant:752].active = YES;
    [detailPanel setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];

    NSStackView *detail = [[NSStackView alloc] init];
    detail.orientation = NSUserInterfaceLayoutOrientationVertical;
    detail.alignment = NSLayoutAttributeWidth;
    detail.spacing = 0;
    detail.translatesAutoresizingMaskIntoConstraints = NO;
    [detailPanel addSubview:detail];
    [NSLayoutConstraint activateConstraints:@[
        [detail.leadingAnchor constraintEqualToAnchor:detailPanel.leadingAnchor],
        [detail.trailingAnchor constraintEqualToAnchor:detailPanel.trailingAnchor],
        [detail.topAnchor constraintEqualToAnchor:detailPanel.topAnchor],
        [detail.bottomAnchor constraintEqualToAnchor:detailPanel.bottomAnchor],
    ]];

    NSView *header = [self settingsPaneHeaderWithTitle:@"总览" subtitle:@"在线状态、额度和最近活动。"];
    [detail addArrangedSubview:header];
    [header.heightAnchor constraintEqualToConstant:48].active = YES;

    self.contentHost = [[NSView alloc] init];
    self.contentHost.wantsLayer = YES;
    self.contentHost.layer.backgroundColor = [CPSettingsContentBackgroundColor() colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace].CGColor;
    self.contentHost.translatesAutoresizingMaskIntoConstraints = NO;
    [detail addArrangedSubview:self.contentHost];

    [self rebuildSettingsPagesSelectingIndex:0];

    NSStackView *buttons = [[NSStackView alloc] init];
    buttons.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    buttons.alignment = NSLayoutAttributeCenterY;
    buttons.spacing = 8;
    buttons.edgeInsets = NSEdgeInsetsMake(6, 14, 6, 14);
    buttons.wantsLayer = YES;
    buttons.layer.backgroundColor = [CPSettingsContentBackgroundColor() colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace].CGColor;
    self.statusLabel = [self detailLabel:@"控制中心已打开"];
    self.statusLabel.maximumNumberOfLines = 1;
    self.statusLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    self.owner.footerStatusLabel = self.statusLabel;
    [buttons addArrangedSubview:self.statusLabel];
    [self.statusLabel setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    self.restoreDefaultsButton = [self button:@"恢复默认值" symbol:@"arrow.counterclockwise" action:@selector(restoreDefaults:)];
    [buttons addArrangedSubview:self.restoreDefaultsButton];
    self.saveSettingsButton = [self button:@"保存设置" symbol:@"checkmark.circle" action:@selector(save:)];
    self.saveSettingsButton.keyEquivalent = @"\r";
    [buttons addArrangedSubview:self.saveSettingsButton];
    [detail addArrangedSubview:buttons];
    [buttons.heightAnchor constraintEqualToConstant:38].active = YES;
    [self renderSettingsSectionAtIndex:self.selectedSettingsIndex];
}

- (BOOL)windowShouldClose:(NSWindow *)sender {
    if (sender != self.window) {
        return YES;
    }
    [self.window orderOut:nil];
    return NO;
}

- (void)windowWillClose:(NSNotification *)notification {
    if (notification.object != self.window) {
        return;
    }
    self.window.delegate = nil;
    self.window = nil;
    self.controls = [NSMutableDictionary dictionary];
    self.scrollViews = [NSMutableArray array];
    self.statusLabel = nil;
    self.serviceLabel = nil;
    self.codexLabel = nil;
    self.baseURLLabel = nil;
    self.diagnosticsLabel = nil;
    self.summaryStatusLabel = nil;
    self.summaryAccountsLabel = nil;
    self.summaryVersionLabel = nil;
    self.overviewFocusServiceLabel = nil;
    self.overviewFocusAccountsLabel = nil;
    self.overviewFocusRepairLabel = nil;
    self.overviewFocusErrorsLabel = nil;
    self.overviewFocusQuotaLabel = nil;
    self.routingCurrentStrategyLabel = nil;
    self.routingCooldownLabel = nil;
    self.routingRefreshLabel = nil;
    self.routingWindowLabel = nil;
    self.codexModeSummaryLabel = nil;
    self.codexBaseSummaryLabel = nil;
    self.codexOpenAIBaseLabel = nil;
    self.codexChatGPTBaseLabel = nil;
    self.codexPortLabel = nil;
    self.codexRestartLabel = nil;
    self.advancedRestartImpactLabel = nil;
    self.advancedStreamImpactLabel = nil;
    self.advancedSessionImpactLabel = nil;
    self.advancedSaveImpactLabel = nil;
    self.runtimeDirLabel = nil;
    self.sourceDirLabel = nil;
    self.frontendVersionLabel = nil;
    self.runtimeVersionLabel = nil;
    self.proxyVersionLabel = nil;
    self.manifestLabel = nil;
    self.detailTitleLabel = nil;
    self.detailSubtitleLabel = nil;
    self.sidebarStatusLabel = nil;
    self.sidebarAccountsLabel = nil;
    self.sidebarVersionLabel = nil;
    self.proxyModeControl = nil;
    self.contentHost = nil;
    self.restoreDefaultsButton = nil;
    self.saveSettingsButton = nil;
    self.menuBarLoginItemControl = nil;
    self.menuBarLoginItemLabel = nil;
    self.settingsNavButtons = [NSMutableArray array];
    self.settingsNavIconViews = [NSMutableArray array];
    self.settingsNavTitleLabels = [NSMutableArray array];
}

- (void)addSettingsPageWithStack:(NSStackView *)stack selected:(BOOL)selected {
    NSScrollView *scroll = [self scrollWithStack:stack];
    scroll.translatesAutoresizingMaskIntoConstraints = NO;
    scroll.hidden = !selected;
    [self.contentHost addSubview:scroll];
    [NSLayoutConstraint activateConstraints:@[
        [scroll.leadingAnchor constraintEqualToAnchor:self.contentHost.leadingAnchor],
        [scroll.trailingAnchor constraintEqualToAnchor:self.contentHost.trailingAnchor],
        [scroll.topAnchor constraintEqualToAnchor:self.contentHost.topAnchor],
        [scroll.bottomAnchor constraintEqualToAnchor:self.contentHost.bottomAnchor],
    ]];
}

- (void)resetPageReferences {
    self.controls = [NSMutableDictionary dictionary];
    self.scrollViews = [NSMutableArray array];
    self.summaryStatusLabel = nil;
    self.summaryAccountsLabel = nil;
    self.summaryVersionLabel = nil;
    self.codexModeSummaryLabel = nil;
    self.codexBaseSummaryLabel = nil;
    self.runtimeDirLabel = nil;
    self.sourceDirLabel = nil;
    self.frontendVersionLabel = nil;
    self.runtimeVersionLabel = nil;
    self.proxyVersionLabel = nil;
    self.manifestLabel = nil;
    self.proxyModeControl = nil;
    self.menuBarLoginItemControl = nil;
    self.menuBarLoginItemLabel = nil;
}

- (void)rebuildSettingsPagesSelectingIndex:(NSInteger)selected {
    if (!self.contentHost) {
        return;
    }
    NSArray *oldViews = self.contentHost.subviews.copy;
    for (NSView *view in oldViews) {
        [view removeFromSuperview];
    }
    [self resetPageReferences];
    selected = MAX(0, MIN(selected, 5));
    NSStackView *page = nil;
    switch (selected) {
        case 1:
            page = [self accountsCenterStack];
            break;
        case 2:
            page = [self routingStack];
            break;
        case 3:
            page = [self proxyStack];
            break;
        case 4:
            page = [self advancedStack];
            break;
        case 5:
            page = [self diagnosticsStack];
            break;
        case 0:
        default:
            page = [self overviewStack];
            break;
    }
    [self addSettingsPageWithStack:page selected:YES];
    [self renderSettingsSectionAtIndex:selected];
    [self scrollAllTabsToTopAfterLayout];
}

- (NSView *)settingsSidebarView {
    NSVisualEffectView *sidebar = [[NSVisualEffectView alloc] init];
    sidebar.material = NSVisualEffectMaterialSidebar;
    sidebar.blendingMode = NSVisualEffectBlendingModeBehindWindow;
    sidebar.state = NSVisualEffectStateActive;
    sidebar.wantsLayer = YES;
    sidebar.layer.backgroundColor = [CPSidebarPanelBackgroundColor() colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace].CGColor;
    sidebar.translatesAutoresizingMaskIntoConstraints = NO;

    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeWidth;
    stack.spacing = 8;
    stack.edgeInsets = NSEdgeInsetsMake(52, 10, 12, 10);
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [sidebar addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:sidebar.leadingAnchor],
        [stack.trailingAnchor constraintEqualToAnchor:sidebar.trailingAnchor],
        [stack.topAnchor constraintEqualToAnchor:sidebar.topAnchor],
        [stack.bottomAnchor constraintEqualToAnchor:sidebar.bottomAnchor],
    ]];

    NSTextField *title = [self label:@"控制中心" size:16 weight:NSFontWeightSemibold color:NSColor.labelColor];
    [stack addArrangedSubview:title];

    [stack addArrangedSubview:[self label:@"管理" size:12 weight:NSFontWeightSemibold color:NSColor.tertiaryLabelColor]];

    NSArray<NSDictionary *> *items = @[
        @{@"title": @"总览", @"symbol": @"chart.pie"},
        @{@"title": @"账号", @"symbol": @"person.2"},
        @{@"title": @"额度与路由", @"symbol": @"speedometer"},
        @{@"title": @"Codex 代理", @"symbol": @"point.3.connected.trianglepath.dotted"},
        @{@"title": @"高级", @"symbol": @"slider.horizontal.3"},
        @{@"title": @"诊断", @"symbol": @"stethoscope"},
    ];
    for (NSInteger i = 0; i < (NSInteger)items.count; i++) {
        NSButton *button = [self settingsSidebarButtonWithTitle:items[i][@"title"] symbol:items[i][@"symbol"] tag:i];
        [stack addArrangedSubview:button];
        [self.settingsNavButtons addObject:button];
    }

    NSView *flex = [[NSView alloc] init];
    [stack addArrangedSubview:flex];
    [flex.heightAnchor constraintGreaterThanOrEqualToConstant:16].active = YES;

    NSStackView *statusStack = [[NSStackView alloc] init];
    statusStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    statusStack.spacing = 3;
    statusStack.translatesAutoresizingMaskIntoConstraints = NO;
    [statusStack.heightAnchor constraintEqualToConstant:54].active = YES;

    [statusStack addArrangedSubview:[self label:@"后台服务" size:11 weight:NSFontWeightSemibold color:NSColor.labelColor]];
    self.sidebarStatusLabel = [self label:@"读取中" size:13 weight:NSFontWeightSemibold color:NSColor.secondaryLabelColor];
    self.sidebarAccountsLabel = [self label:@"账号 -" size:11 weight:NSFontWeightRegular color:NSColor.secondaryLabelColor];
    self.sidebarVersionLabel = [self label:@"版本 -" size:11 weight:NSFontWeightRegular color:NSColor.secondaryLabelColor];
    self.sidebarStatusLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    self.sidebarAccountsLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    self.sidebarVersionLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    [statusStack addArrangedSubview:self.sidebarStatusLabel];
    [statusStack addArrangedSubview:self.sidebarAccountsLabel];
    [statusStack addArrangedSubview:self.sidebarVersionLabel];
    [stack addArrangedSubview:statusStack];

    return sidebar;
}

- (NSButton *)settingsSidebarButtonWithTitle:(NSString *)title symbol:(NSString *)symbol tag:(NSInteger)tag {
    NSButton *button = [NSButton buttonWithTitle:@"" target:self action:@selector(settingsSidebarAction:)];
    [button setButtonType:NSButtonTypeToggle];
    button.bezelStyle = NSBezelStyleRegularSquare;
    button.bordered = NO;
    button.controlSize = NSControlSizeRegular;
    button.tag = tag;
    button.wantsLayer = YES;
    button.layer.cornerRadius = 8;
    button.layer.masksToBounds = YES;
    button.translatesAutoresizingMaskIntoConstraints = NO;
    [button.heightAnchor constraintEqualToConstant:34].active = YES;

    NSImageView *iconView = [[NSImageView alloc] init];
    iconView.translatesAutoresizingMaskIntoConstraints = NO;
    iconView.imageScaling = NSImageScaleProportionallyDown;
    iconView.contentTintColor = NSColor.secondaryLabelColor;
    NSImage *image = [self symbolImageNamed:symbol];
    if (image) {
        image.template = YES;
        iconView.image = image;
    }

    NSTextField *titleLabel = [self label:title size:14 weight:NSFontWeightMedium color:NSColor.secondaryLabelColor];
    titleLabel.alignment = NSTextAlignmentLeft;
    titleLabel.maximumNumberOfLines = 1;

    [button addSubview:iconView];
    [button addSubview:titleLabel];
    [NSLayoutConstraint activateConstraints:@[
        [iconView.leadingAnchor constraintEqualToAnchor:button.leadingAnchor constant:10],
        [iconView.centerYAnchor constraintEqualToAnchor:button.centerYAnchor],
        [iconView.widthAnchor constraintEqualToConstant:16],
        [iconView.heightAnchor constraintEqualToConstant:16],

        [titleLabel.leadingAnchor constraintEqualToAnchor:iconView.trailingAnchor constant:8],
        [titleLabel.trailingAnchor constraintEqualToAnchor:button.trailingAnchor constant:-8],
        [titleLabel.centerYAnchor constraintEqualToAnchor:button.centerYAnchor],
    ]];
    [self.settingsNavIconViews addObject:iconView];
    [self.settingsNavTitleLabels addObject:titleLabel];
    return button;
}

- (void)settingsSidebarAction:(NSButton *)sender {
    [self rebuildSettingsPagesSelectingIndex:sender.tag];
}

- (void)renderSettingsSectionAtIndex:(NSInteger)selected {
    NSArray<NSDictionary *> *headers = @[
        @{@"title": @"总览", @"subtitle": @"在线状态、额度、Token 使用和最近活动。"},
        @{@"title": @"账号", @"subtitle": @"添加、导入、启用、刷新和清理账号。"},
        @{@"title": @"额度与路由", @"subtitle": @"管理额度刷新、路由策略和账号选择解释。"},
        @{@"title": @"Codex 代理", @"subtitle": @"切换 Codex 请求是否经过账号池代理。"},
        @{@"title": @"高级", @"subtitle": @"调整代理、网络、流式响应和会话行为。"},
        @{@"title": @"诊断", @"subtitle": @"检查运行目录、资源版本和诊断文件。"},
    ];
    selected = MAX(0, MIN(selected, (NSInteger)headers.count - 1));
    self.selectedSettingsIndex = selected;
    for (NSInteger i = 0; i < (NSInteger)self.scrollViews.count; i++) {
        NSScrollView *scroll = self.scrollViews[i];
        if (!scroll.hidden) {
            [self scrollViewToTop:scroll];
        }
    }
    for (NSButton *button in self.settingsNavButtons) {
        BOOL active = button.tag == selected;
        button.state = active ? NSControlStateValueOn : NSControlStateValueOff;
        NSColor *background = active ? [NSColor colorWithCalibratedWhite:0.0 alpha:0.08] : NSColor.clearColor;
        NSColor *rgb = [background colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace] ?: background;
        button.layer.backgroundColor = rgb.CGColor;
        NSColor *tint = active ? NSColor.labelColor : NSColor.secondaryLabelColor;
        NSInteger index = [self.settingsNavButtons indexOfObject:button];
        if (index != NSNotFound && index < (NSInteger)self.settingsNavIconViews.count) {
            self.settingsNavIconViews[index].contentTintColor = tint;
        }
        if (index != NSNotFound && index < (NSInteger)self.settingsNavTitleLabels.count) {
            self.settingsNavTitleLabels[index].textColor = tint;
        }
    }
    BOOL showsConfigActions = selected == 2 || selected == 3 || selected == 4;
    self.restoreDefaultsButton.hidden = !showsConfigActions;
    self.saveSettingsButton.hidden = !showsConfigActions;
    self.statusLabel.stringValue = showsConfigActions ? @"修改后点击保存设置生效" : @"控制中心已打开";
    if (selected < (NSInteger)headers.count) {
        self.detailTitleLabel.stringValue = CPString(headers[selected][@"title"]);
        self.detailSubtitleLabel.stringValue = CPString(headers[selected][@"subtitle"]);
    }
}

- (NSScrollView *)scrollWithStack:(NSStackView *)stack {
    NSScrollView *scroll = [[NSScrollView alloc] init];
    scroll.drawsBackground = NO;
    scroll.hasVerticalScroller = YES;
    scroll.autohidesScrollers = YES;
    NSView *document = [[CPFlippedView alloc] init];
    document.translatesAutoresizingMaskIntoConstraints = NO;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [document addSubview:stack];
    scroll.documentView = document;
    [NSLayoutConstraint activateConstraints:@[
        [document.widthAnchor constraintEqualToAnchor:scroll.contentView.widthAnchor],
        [document.heightAnchor constraintGreaterThanOrEqualToAnchor:scroll.contentView.heightAnchor],
        [stack.topAnchor constraintEqualToAnchor:document.topAnchor constant:8],
        [stack.leadingAnchor constraintEqualToAnchor:document.leadingAnchor constant:16],
        [stack.trailingAnchor constraintEqualToAnchor:document.trailingAnchor constant:-16],
        [stack.widthAnchor constraintEqualToConstant:720],
        [document.bottomAnchor constraintGreaterThanOrEqualToAnchor:stack.bottomAnchor constant:10],
    ]];
    NSLayoutConstraint *contentBottom = [document.bottomAnchor constraintEqualToAnchor:stack.bottomAnchor constant:10];
    contentBottom.priority = NSLayoutPriorityDefaultHigh;
    contentBottom.active = YES;
    for (NSView *view in stack.arrangedSubviews) {
        view.translatesAutoresizingMaskIntoConstraints = NO;
        [view.widthAnchor constraintEqualToAnchor:stack.widthAnchor].active = YES;
    }
    [self.scrollViews addObject:scroll];
    return scroll;
}

- (NSStackView *)baseStack {
    NSStackView *stack = [[CPFlippedStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.distribution = NSStackViewDistributionFill;
    stack.alignment = NSLayoutAttributeWidth;
    stack.spacing = 10;
    stack.edgeInsets = NSEdgeInsetsMake(0, 0, 0, 0);
    return stack;
}

- (NSStackView *)settingsMainSideWithMain:(NSView *)main side:(NSView *)side sideWidth:(CGFloat)sideWidth {
    (void)sideWidth;
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeTop;
    row.distribution = NSStackViewDistributionFillEqually;
    row.spacing = 12;
    [row addArrangedSubview:main];
    [row addArrangedSubview:side];
    [main setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    [side setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    return row;
}

- (NSStackView *)overviewMainStack {
    NSStackView *main = [self baseStack];
    main.spacing = 10;
    [main addArrangedSubview:[self.owner metricsRow]];
    [main addArrangedSubview:[self.owner totalQuotaCard]];
    [main addArrangedSubview:[self.owner tokenStatsCard]];
    [main addArrangedSubview:[self.owner tokenBarChartCard]];
    [main addArrangedSubview:[self.owner tokenHeatmapCard]];
    [main addArrangedSubview:[self.owner recentRequestsCard]];
    return main;
}

- (NSStackView *)overviewInsightStack {
    NSStackView *side = [self baseStack];
    side.spacing = 16;
    self.overviewFocusServiceLabel = [self detailLabel:@"-"];
    self.overviewFocusAccountsLabel = [self detailLabel:@"-"];
    self.overviewFocusRepairLabel = [self detailLabel:@"-"];
    self.overviewFocusErrorsLabel = [self detailLabel:@"-"];
    self.overviewFocusQuotaLabel = [self detailLabel:@"-"];
    [side addArrangedSubview:[self settingsSectionWithTitle:@"今日重点"
                                                    summary:nil
                                                      views:@[
        [self compactInfoRowWithTitle:@"后台" label:self.overviewFocusServiceLabel],
        [self compactInfoRowWithTitle:@"账号" label:self.overviewFocusAccountsLabel],
        [self compactInfoRowWithTitle:@"修复" label:self.overviewFocusRepairLabel],
        [self compactInfoRowWithTitle:@"错误" label:self.overviewFocusErrorsLabel],
        [self compactInfoRowWithTitle:@"额度" label:self.overviewFocusQuotaLabel],
    ]]];
    [side addArrangedSubview:[self settingsSectionWithTitle:@"快捷操作"
                                                    summary:nil
                                                      views:@[
        [self buttonGridWithButtons:@[
            [self ownerButton:@"刷新后台" symbol:@"arrow.clockwise" action:@selector(refreshSnapshots:)],
            [self ownerButton:@"启动/修复" symbol:@"play.circle.fill" action:@selector(repairAction:)],
            [self ownerButton:@"打开 Codex" symbol:@"arrow.up.forward.app" action:@selector(openCodexAction:)],
            [self ownerButton:@"Web 控制台" symbol:@"safari" action:@selector(openWebAction:)],
        ] columns:2],
    ]]];
    return side;
}

- (NSStackView *)overviewQuotaTokenStack {
    NSStackView *left = [self baseStack];
    left.spacing = 8;
    [left addArrangedSubview:[self.owner totalQuotaCard]];
    [left addArrangedSubview:[self.owner tokenStatsCard]];
    return left;
}

- (NSStackView *)overviewStack {
    NSStackView *stack = [self baseStack];
    [stack addArrangedSubview:[self.owner metricsRow]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:[self overviewQuotaTokenStack]
                                                        right:[self overviewInsightStack]]];
    [stack addArrangedSubview:[self.owner tokenBarChartCard]];
    [stack addArrangedSubview:[self.owner tokenHeatmapCard]];
    [stack addArrangedSubview:[self.owner recentRequestsCard]];
    return stack;
}

- (NSStackView *)accountsCenterStack {
    NSStackView *stack = [self baseStack];
    [stack addArrangedSubview:[self.owner accountManagementCard]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:[self.owner totalQuotaCard]
                                                        right:[self.owner selectionExplanationCard]]];
    return stack;
}

- (NSStackView *)routingStack {
    NSStackView *stack = [self baseStack];
    NSView *strategy = [self settingsSectionWithTitle:@"选择策略"
                                              summary:nil
                                                views:@[
        [self popupRow:@"选择策略" key:@"rotation_strategy" titles:@[@"额度优先", @"轮询"] values:@[@"most_available", @"round_robin"]],
        [self settingsNoteLabel:@"额度优先会尽量使用剩余额度更高的账号。"],
    ]];
    NSView *refresh = [self settingsSectionWithTitle:@"额度刷新"
                                             summary:nil
                                               views:@[
        [self boolRow:@"自动刷新额度" key:@"quota_tracker_enabled"],
        [self integerRow:@"间隔（秒）" key:@"quota_refresh_interval" min:30 max:86400],
        [self numberRow:@"5h 权重" key:@"quota_weight_5h" min:0 max:1 decimals:3],
        [self numberRow:@"7d 权重" key:@"quota_weight_7d" min:0 max:1 decimals:3],
    ]];
    self.routingCurrentStrategyLabel = [self detailLabel:@"-"];
    self.routingCooldownLabel = [self detailLabel:@"-"];
    self.routingRefreshLabel = [self detailLabel:@"-"];
    self.routingWindowLabel = [self detailLabel:@"-"];
    NSView *routeState = [self settingsSectionWithTitle:@"路由解释"
                                                summary:nil
                                                  views:@[
        [self compactInfoRowWithTitle:@"当前策略" label:self.routingCurrentStrategyLabel],
        [self compactInfoRowWithTitle:@"冷却账号" label:self.routingCooldownLabel],
        [self compactInfoRowWithTitle:@"额度刷新" label:self.routingRefreshLabel],
        [self compactInfoRowWithTitle:@"窗口权重" label:self.routingWindowLabel],
        [self settingsNoteLabel:@"额度优先会先看可用性，再参考 5h 与 7d 剩余额度；额度数据缺失时自动退回可用账号轮换。"],
    ]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:[self.owner totalQuotaCard]
                                                        right:routeState]];
    [stack addArrangedSubview:[self.owner quotaCard]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:strategy right:refresh]];
    [stack addArrangedSubview:[self.owner selectionExplanationCard]];
    return stack;
}

- (NSStackView *)generalStack {
    NSStackView *stack = [self baseStack];
    self.summaryStatusLabel = [self summaryValueLabel:@"读取中"];
    self.summaryAccountsLabel = [self summaryValueLabel:@"-"];
    self.summaryVersionLabel = [self summaryValueLabel:@"-"];
    [stack addArrangedSubview:[self settingsSummaryStripWithItems:@[
        @{@"title": @"后台", @"label": self.summaryStatusLabel},
        @{@"title": @"可用账号", @"label": self.summaryAccountsLabel},
        @{@"title": @"版本", @"label": self.summaryVersionLabel},
    ]]];

    self.serviceLabel = [self detailLabel:@"正在读取后台状态..."];
    NSView *serviceSection = [self settingsSectionWithTitle:@"后台服务"
                                                    summary:nil
                                                      views:@[
        [self compactInfoRowWithTitle:@"状态" label:self.serviceLabel],
        [self settingsNoteLabel:@"后台在线后，Codex 请求会由账号池代理接管。"],
    ]];
    NSView *logSection = [self settingsSectionWithTitle:@"日志"
                                                summary:nil
                                                  views:@[
        [self popupRow:@"级别" key:@"log_level" titles:@[@"DEBUG", @"INFO", @"WARNING", @"ERROR", @"CRITICAL"] values:@[@"DEBUG", @"INFO", @"WARNING", @"ERROR", @"CRITICAL"]],
        [self settingsNoteLabel:@"DEBUG 更详细，但日志文件会增长更快。"],
    ]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:serviceSection right:logSection]];

    [stack addArrangedSubview:[self settingsSectionWithTitle:@"快捷操作"
                                                      summary:nil
                                                        views:@[
        [self buttonGridWithButtons:@[
            [self ownerButton:@"打开日志" symbol:@"doc.text.magnifyingglass" action:@selector(openLogAction:)],
            [self ownerButton:@"路径与依赖" symbol:@"folder.badge.gearshape" action:@selector(showPathsAction:)],
            [self ownerButton:@"打开 Web 控制台" symbol:@"safari" action:@selector(openWebAction:)],
        ] columns:3],
    ]]];
    return stack;
}

- (NSStackView *)proxyStack {
    NSStackView *stack = [self baseStack];
    [stack addArrangedSubview:[self.owner proxyConfirmationCard]];
    [stack addArrangedSubview:[self.owner configCardsRow]];
    self.proxyModeControl = [[NSSegmentedControl alloc] init];
    self.proxyModeControl.segmentCount = 2;
    [self.proxyModeControl setLabel:@"账号池代理" forSegment:0];
    [self.proxyModeControl setLabel:@"直连" forSegment:1];
    self.proxyModeControl.segmentStyle = NSSegmentStyleRounded;
    self.proxyModeControl.selectedSegment = 0;
    self.proxyModeControl.translatesAutoresizingMaskIntoConstraints = NO;
    [self.proxyModeControl.widthAnchor constraintEqualToConstant:192].active = YES;

    self.codexLabel = [self detailLabel:@"正在读取 Codex 配置..."];
    self.baseURLLabel = [self detailLabel:@"-"];
    self.codexModeSummaryLabel = [self summaryValueLabel:@"-"];
    self.codexBaseSummaryLabel = [self summaryValueLabel:@"-"];
    NSView *proxyControls = [self settingsSectionWithTitle:@"Codex 代理"
                                                   summary:nil
                                                     views:@[
        [self rowWithTitle:@"模式" control:self.proxyModeControl],
        [self infoRow:@"当前配置" label:self.codexLabel],
        [self infoRow:@"Base URL" label:self.baseURLLabel],
        [self integerRow:@"代理端口" key:@"port" min:1024 max:65535],
        [self settingsNoteLabel:@"切换代理模式会更新 Codex 配置；端口变更保存后需要重启后台生效。"],
    ]];
    self.codexOpenAIBaseLabel = [self detailLabel:@"-"];
    self.codexChatGPTBaseLabel = [self detailLabel:@"-"];
    self.codexPortLabel = [self detailLabel:@"-"];
    self.codexRestartLabel = [self detailLabel:@"-"];
    NSView *effectiveConfig = [self settingsSectionWithTitle:@"当前生效配置"
                                                     summary:nil
                                                       views:@[
        [self compactInfoRowWithTitle:@"OpenAI" label:self.codexOpenAIBaseLabel],
        [self compactInfoRowWithTitle:@"ChatGPT" label:self.codexChatGPTBaseLabel],
        [self compactInfoRowWithTitle:@"端口" label:self.codexPortLabel],
        [self compactInfoRowWithTitle:@"重启" label:self.codexRestartLabel],
        [self settingsNoteLabel:@"保存后会优先通过后台 API 热应用；端口、运行时和 LaunchAgent 问题会在诊断页继续提示。"],
    ]];
    [stack addArrangedSubview:[self settingsSummaryStripWithItems:@[
        @{@"title": @"当前模式", @"label": self.codexModeSummaryLabel},
        @{@"title": @"Base URL", @"label": self.codexBaseSummaryLabel},
    ]]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:proxyControls right:effectiveConfig]];
    [stack addArrangedSubview:[self.owner recentRequestsCard]];
    return stack;
}

- (NSStackView *)quotaStack {
    NSStackView *stack = [self baseStack];
    NSView *strategy = [self settingsSectionWithTitle:@"选择策略"
                                              summary:nil
                                                views:@[
        [self popupRow:@"选择策略" key:@"rotation_strategy" titles:@[@"额度优先", @"轮询"] values:@[@"most_available", @"round_robin"]],
        [self settingsNoteLabel:@"额度优先会尽量使用剩余额度更高的账号。"],
    ]];
    NSView *refresh = [self settingsSectionWithTitle:@"额度刷新"
                                             summary:nil
                                               views:@[
        [self boolRow:@"自动刷新额度" key:@"quota_tracker_enabled"],
        [self integerRow:@"间隔（秒）" key:@"quota_refresh_interval" min:30 max:86400],
        [self numberRow:@"5h 权重" key:@"quota_weight_5h" min:0 max:1 decimals:3],
        [self numberRow:@"7d 权重" key:@"quota_weight_7d" min:0 max:1 decimals:3],
    ]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:strategy right:refresh]];
    return stack;
}

- (NSStackView *)advancedStack {
    NSStackView *stack = [self baseStack];
    NSView *behavior = [self settingsSectionWithTitle:@"代理行为"
                                              summary:nil
                                                views:@[
        [self popupRow:@"产品模式" key:@"product_mode" titles:@[@"标准", @"兼容", @"诊断"] values:@[@"standard", @"compatibility", @"diagnostic"]],
        [self popupRow:@"流模式" key:@"codex_stream_mode" titles:@[@"实时", @"缓冲", @"混合"] values:@[@"realtime", @"buffered", @"hybrid"]],
        [self integerRow:@"限流冷却" key:@"rate_limit_cooldown" min:1 max:3600],
        [self integerRow:@"最大重试" key:@"max_retries" min:1 max:50],
        [self integerRow:@"请求上限 MB" key:@"max_request_body_mb" min:1 max:1024],
    ]];

    NSView *network = [self settingsSectionWithTitle:@"上游网络"
                                             summary:nil
                                               views:@[
        [self integerRow:@"连接超时" key:@"upstream_connect_timeout_sec" min:1 max:60],
        [self integerRow:@"瞬时重试" key:@"upstream_transient_retries" min:0 max:5],
        [self integerRow:@"退避（ms）" key:@"upstream_transient_backoff_ms" min:0 max:5000],
    ]];

    NSView *stream = [self settingsSectionWithTitle:@"流与会话"
                                            summary:nil
                                              views:@[
        [self integerRow:@"探测秒" key:@"codex_hybrid_probe_seconds" min:0 max:120],
        [self integerRow:@"探测 bytes" key:@"codex_hybrid_probe_bytes" min:1024 max:10485760],
        [self integerRow:@"流重试冷却" key:@"codex_stream_retry_cooldown" min:0 max:3600],
        [self integerRow:@"Stream keepalive" key:@"stream_keepalive_seconds" min:0 max:300],
        [self integerRow:@"Bootstrap retries" key:@"stream_bootstrap_retries" min:0 max:5],
        [self integerRow:@"Nonstream keepalive" key:@"nonstream_keepalive_interval" min:0 max:300],
        [self integerRow:@"WebSocket heartbeat" key:@"websocket_heartbeat_seconds" min:0 max:300],
        [self boolRow:@"Session affinity" key:@"session_affinity_enabled"],
        [self integerRow:@"Affinity TTL（秒）" key:@"session_affinity_ttl_seconds" min:60 max:86400],
    ]];
    self.menuBarLoginItemControl = [NSButton checkboxWithTitle:@"登录后自动常驻菜单栏" target:nil action:nil];
    self.menuBarLoginItemControl.translatesAutoresizingMaskIntoConstraints = NO;
    self.menuBarLoginItemLabel = [self detailLabel:@"正在读取菜单栏登录项..."];
    NSView *startup = [self settingsSectionWithTitle:@"启动与菜单栏"
                                             summary:nil
                                               views:@[
        [self rowWithTitle:@"菜单栏" control:self.menuBarLoginItemControl],
        [self compactInfoRowWithTitle:@"状态" label:self.menuBarLoginItemLabel],
        [self settingsNoteLabel:@"手动打开 App 会显示控制中心；登录项启动只常驻菜单栏，不主动弹窗。"],
    ]];
    self.advancedRestartImpactLabel = [self detailLabel:@"-"];
    self.advancedStreamImpactLabel = [self detailLabel:@"-"];
    self.advancedSessionImpactLabel = [self detailLabel:@"-"];
    self.advancedSaveImpactLabel = [self detailLabel:@"-"];
    NSView *impact = [self settingsSectionWithTitle:@"变更影响"
                                            summary:nil
                                              views:@[
        [self compactInfoRowWithTitle:@"重启" label:self.advancedRestartImpactLabel],
        [self compactInfoRowWithTitle:@"流式" label:self.advancedStreamImpactLabel],
        [self compactInfoRowWithTitle:@"会话" label:self.advancedSessionImpactLabel],
        [self compactInfoRowWithTitle:@"保存" label:self.advancedSaveImpactLabel],
        [self settingsNoteLabel:@"高级项保留当前行为边界：保存配置，不新增后台能力；需要重启的项目由诊断和状态栏继续提示。"],
    ]];
    NSView *troubleshoot = [self settingsSectionWithTitle:@"排障入口"
                                                  summary:nil
                                                    views:@[
        [self buttonGridWithButtons:@[
            [self ownerButton:@"打开日志" symbol:@"doc.text.magnifyingglass" action:@selector(openLogAction:)],
            [self ownerButton:@"路径与依赖" symbol:@"folder.badge.gearshape" action:@selector(showPathsAction:)],
        ] columns:2],
    ]];
    NSStackView *impactSide = [self baseStack];
    impactSide.spacing = 8;
    [impactSide addArrangedSubview:startup];
    [impactSide addArrangedSubview:impact];
    [impactSide addArrangedSubview:troubleshoot];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:behavior right:network]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:stream right:impactSide]];
    return stack;
}

- (NSStackView *)diagnosticsStack {
    NSStackView *stack = [self baseStack];
    if ([self.owner hasRuntimeManifestMismatch] || [self.owner hasVersionMismatch] || [self.owner hasUsageStorageMismatch]) {
        [stack addArrangedSubview:[self.owner runtimeSyncCard]];
    }
    [stack addArrangedSubview:[self.owner configCardsRow]];
    [stack addArrangedSubview:[self settingsTwoColumnWithLeft:[self.owner updateDiagnosticsCard]
                                                        right:[self.owner pathsCard]]];
    self.runtimeDirLabel = [self detailLabel:@"-"];
    self.sourceDirLabel = [self detailLabel:@"-"];
    self.frontendVersionLabel = [self detailLabel:@"-"];
    self.runtimeVersionLabel = [self detailLabel:@"-"];
    self.proxyVersionLabel = [self detailLabel:@"-"];
    self.manifestLabel = [self detailLabel:@"-"];
    [stack addArrangedSubview:[self settingsSectionWithTitle:@"路径与版本"
                                                      summary:nil
                                                        views:@[
        [self compactInfoRowWithTitle:@"运行目录" label:self.runtimeDirLabel],
        [self compactInfoRowWithTitle:@"资源目录" label:self.sourceDirLabel],
        [self pairedRowsWithLeft:[self compactInfoRowWithTitle:@"前台版本" label:self.frontendVersionLabel]
                            right:[self compactInfoRowWithTitle:@"运行版本" label:self.runtimeVersionLabel]],
        [self pairedRowsWithLeft:[self compactInfoRowWithTitle:@"后台版本" label:self.proxyVersionLabel]
                            right:[self compactInfoRowWithTitle:@"Manifest" label:self.manifestLabel]],
        [self buttonGridWithButtons:@[
        [self ownerButton:@"打开日志" symbol:@"doc.text.magnifyingglass" action:@selector(openLogAction:)],
        [self ownerButton:@"打开结果文件" symbol:@"doc" action:@selector(openResultAction:)],
        [self ownerButton:@"路径与依赖" symbol:@"folder.badge.gearshape" action:@selector(showPathsAction:)],
        ] columns:2],
    ]]];
    [stack addArrangedSubview:[self.owner logCardWithHeight:150 actions:NO]];
    return stack;
}

- (NSTextField *)label:(NSString *)text size:(CGFloat)size weight:(NSFontWeight)weight color:(NSColor *)color {
    NSTextField *label = [NSTextField labelWithString:text ?: @""];
    label.font = [NSFont systemFontOfSize:size weight:weight];
    label.textColor = color ?: NSColor.labelColor;
    label.lineBreakMode = NSLineBreakByWordWrapping;
    label.maximumNumberOfLines = 0;
    label.translatesAutoresizingMaskIntoConstraints = NO;
    return label;
}

- (NSTextField *)sectionLabel:(NSString *)text {
    return [self label:text size:13 weight:NSFontWeightSemibold color:NSColor.labelColor];
}

- (NSTextField *)detailLabel:(NSString *)text {
    return [self label:text size:12 weight:NSFontWeightRegular color:NSColor.secondaryLabelColor];
}

- (NSTextField *)summaryValueLabel:(NSString *)text {
    NSTextField *label = [self label:text size:13 weight:NSFontWeightSemibold color:NSColor.labelColor];
    label.alignment = NSTextAlignmentCenter;
    label.lineBreakMode = NSLineBreakByTruncatingTail;
    label.maximumNumberOfLines = 1;
    return label;
}

- (NSView *)separatorView {
    NSBox *box = [[NSBox alloc] init];
    box.boxType = NSBoxSeparator;
    box.translatesAutoresizingMaskIntoConstraints = NO;
    [box.heightAnchor constraintEqualToConstant:1].active = YES;
    return box;
}

- (NSView *)verticalSeparatorView {
    NSBox *box = [[NSBox alloc] init];
    box.boxType = NSBoxSeparator;
    box.translatesAutoresizingMaskIntoConstraints = NO;
    [box.widthAnchor constraintEqualToConstant:1].active = YES;
    return box;
}

- (NSView *)settingsPaneHeaderWithTitle:(NSString *)title subtitle:(NSString *)subtitle {
    CPThemedView *header = [[CPThemedView alloc] init];
    header.wantsLayer = YES;
    header.cpBackgroundColor = CPSettingsHeaderBackgroundColor();
    header.cpBorderColor = NSColor.clearColor;
    header.layer.borderWidth = 0;
    header.layer.cornerRadius = 16;
    header.layer.masksToBounds = YES;
    if (@available(macOS 10.13, *)) {
        header.layer.maskedCorners = kCALayerMinXMinYCorner | kCALayerMinXMaxYCorner;
    }
    header.translatesAutoresizingMaskIntoConstraints = NO;

    NSStackView *textStack = [[NSStackView alloc] init];
    textStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    textStack.alignment = NSLayoutAttributeLeading;
    textStack.spacing = 3;
    textStack.translatesAutoresizingMaskIntoConstraints = NO;
    [header addSubview:textStack];

    self.detailTitleLabel = [self label:title size:18 weight:NSFontWeightBold color:NSColor.labelColor];
    self.detailSubtitleLabel = [self label:subtitle size:12 weight:NSFontWeightRegular color:NSColor.secondaryLabelColor];
    self.detailSubtitleLabel.maximumNumberOfLines = 1;
    self.detailSubtitleLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    [textStack addArrangedSubview:self.detailTitleLabel];
    [textStack addArrangedSubview:self.detailSubtitleLabel];

    NSButton *refresh = [self iconButtonWithSymbol:@"arrow.clockwise" tooltip:@"刷新设置" action:@selector(refresh:)];
    [header addSubview:refresh];

    [NSLayoutConstraint activateConstraints:@[
        [textStack.leadingAnchor constraintEqualToAnchor:header.leadingAnchor constant:18],
        [textStack.centerYAnchor constraintEqualToAnchor:header.centerYAnchor],
        [textStack.trailingAnchor constraintLessThanOrEqualToAnchor:refresh.leadingAnchor constant:-12],
        [refresh.trailingAnchor constraintEqualToAnchor:header.trailingAnchor constant:-16],
        [refresh.centerYAnchor constraintEqualToAnchor:header.centerYAnchor],
    ]];
    return header;
}

- (NSButton *)iconButtonWithSymbol:(NSString *)symbol tooltip:(NSString *)tooltip action:(SEL)action {
    NSButton *button = [NSButton buttonWithTitle:@"" target:self action:action];
    button.bezelStyle = NSBezelStyleRounded;
    button.controlSize = NSControlSizeSmall;
    button.imagePosition = NSImageOnly;
    button.toolTip = tooltip;
    button.translatesAutoresizingMaskIntoConstraints = NO;
    NSImage *image = [self symbolImageNamed:symbol];
    if (image) {
        button.image = image;
    }
    [button.widthAnchor constraintEqualToConstant:28].active = YES;
    [button.heightAnchor constraintEqualToConstant:26].active = YES;
    return button;
}

- (NSButton *)button:(NSString *)title symbol:(NSString *)symbol action:(SEL)action {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
    button.bezelStyle = NSBezelStyleRounded;
    button.controlSize = NSControlSizeRegular;
    button.imagePosition = NSImageLeading;
    button.font = [NSFont systemFontOfSize:13 weight:NSFontWeightRegular];
    button.translatesAutoresizingMaskIntoConstraints = NO;
    NSImage *image = [self symbolImageNamed:symbol];
    if (image) {
        button.image = image;
    }
    [button.heightAnchor constraintEqualToConstant:30].active = YES;
    return button;
}

- (NSButton *)ownerButton:(NSString *)title symbol:(NSString *)symbol action:(SEL)action {
    NSButton *button = [self button:title symbol:symbol action:@selector(ownerButtonAction:)];
    button.target = self;
    button.identifier = NSStringFromSelector(action);
    return button;
}

- (void)ownerButtonAction:(NSButton *)sender {
    SEL selector = NSSelectorFromString(CPString(sender.identifier));
    if (selector == @selector(repairAction:)) {
        [self.owner repairAction:sender];
    } else if (selector == @selector(refreshSnapshots:)) {
        [self.owner refreshSnapshots:sender];
    } else if (selector == @selector(openCodexAction:)) {
        [self.owner openCodexAction:sender];
    } else if (selector == @selector(openWebAction:)) {
        [self.owner openWebAction:sender];
    } else if (selector == @selector(openLogAction:)) {
        [self.owner openLogAction:sender];
    } else if (selector == @selector(openResultAction:)) {
        [self.owner openResultAction:sender];
    } else if (selector == @selector(showPathsAction:)) {
        [self.owner showPathsAction:sender];
    }
}

- (NSImage *)symbolImageNamed:(NSString *)name {
    if (@available(macOS 11.0, *)) {
        return [NSImage imageWithSystemSymbolName:name accessibilityDescription:name];
    }
    return nil;
}

- (NSStackView *)rowWithTitle:(NSString *)title control:(NSView *)control {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.spacing = 8;
    NSTextField *label = [self label:title size:12 weight:NSFontWeightMedium color:NSColor.secondaryLabelColor];
    label.alignment = NSTextAlignmentLeft;
    [label.widthAnchor constraintEqualToConstant:78].active = YES;
    [row addArrangedSubview:label];
    [row addArrangedSubview:control];
    [row addArrangedSubview:[[NSView alloc] init]];
    return row;
}

- (NSStackView *)infoRow:(NSString *)title label:(NSTextField *)valueLabel {
    valueLabel.textColor = NSColor.secondaryLabelColor;
    valueLabel.font = [NSFont systemFontOfSize:12 weight:NSFontWeightRegular];
    valueLabel.maximumNumberOfLines = 0;
    [valueLabel setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    return [self rowWithTitle:title control:valueLabel];
}

- (NSStackView *)compactInfoRowWithTitle:(NSString *)title label:(NSTextField *)valueLabel {
    valueLabel.textColor = NSColor.secondaryLabelColor;
    valueLabel.font = [NSFont systemFontOfSize:11 weight:NSFontWeightRegular];
    valueLabel.lineBreakMode = NSLineBreakByWordWrapping;
    valueLabel.maximumNumberOfLines = 2;
    [valueLabel setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    return [self rowWithTitle:title control:valueLabel];
}

- (NSTextField *)settingsNoteLabel:(NSString *)text {
    NSTextField *label = [self label:text size:11 weight:NSFontWeightRegular color:NSColor.tertiaryLabelColor];
    label.maximumNumberOfLines = 2;
    return label;
}

- (NSView *)settingsSummaryStripWithItems:(NSArray<NSDictionary *> *)items {
    CPThemedView *strip = [[CPThemedView alloc] init];
    strip.wantsLayer = YES;
    strip.layer.cornerRadius = 0;
    strip.layer.borderWidth = 0;
    strip.cpBackgroundColor = NSColor.clearColor;
    strip.cpBorderColor = NSColor.clearColor;
    strip.translatesAutoresizingMaskIntoConstraints = NO;
    [strip.heightAnchor constraintEqualToConstant:52].active = YES;

    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.distribution = NSStackViewDistributionFillEqually;
    row.spacing = 0;
    row.translatesAutoresizingMaskIntoConstraints = NO;
    [strip addSubview:row];
    [NSLayoutConstraint activateConstraints:@[
        [row.leadingAnchor constraintEqualToAnchor:strip.leadingAnchor],
        [row.trailingAnchor constraintEqualToAnchor:strip.trailingAnchor],
        [row.topAnchor constraintEqualToAnchor:strip.topAnchor constant:4],
        [row.bottomAnchor constraintEqualToAnchor:strip.bottomAnchor constant:-4],
    ]];

    for (NSDictionary *item in items) {
        NSStackView *cell = [[NSStackView alloc] init];
        cell.orientation = NSUserInterfaceLayoutOrientationVertical;
        cell.alignment = NSLayoutAttributeCenterX;
        cell.spacing = 2;
        NSTextField *title = [self label:CPString(item[@"title"]) size:10 weight:NSFontWeightMedium color:NSColor.secondaryLabelColor];
        title.alignment = NSTextAlignmentCenter;
        [cell addArrangedSubview:title];
        NSTextField *value = [item[@"label"] isKindOfClass:NSTextField.class] ? item[@"label"] : [self summaryValueLabel:@"-"];
        [cell addArrangedSubview:value];
        [row addArrangedSubview:cell];
    }
    return strip;
}

- (NSStackView *)settingsTwoColumnWithLeft:(NSView *)left right:(NSView *)right {
    NSStackView *columns = [[NSStackView alloc] init];
    columns.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    columns.alignment = NSLayoutAttributeTop;
    columns.distribution = NSStackViewDistributionFillEqually;
    columns.spacing = 10;
    [columns addArrangedSubview:left];
    [columns addArrangedSubview:right];
    [left.widthAnchor constraintEqualToAnchor:columns.widthAnchor multiplier:0.5 constant:-5].active = YES;
    [right.widthAnchor constraintEqualToAnchor:columns.widthAnchor multiplier:0.5 constant:-5].active = YES;
    return columns;
}

- (NSStackView *)pairedRowsWithLeft:(NSView *)left right:(NSView *)right {
    NSStackView *row = [[NSStackView alloc] init];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.distribution = NSStackViewDistributionFillEqually;
    row.spacing = 10;
    [row addArrangedSubview:left];
    [row addArrangedSubview:right];
    return row;
}

- (NSStackView *)settingsSectionWithTitle:(NSString *)title summary:(NSString *)summary views:(NSArray<NSView *> *)views {
    NSStackView *section = [[NSStackView alloc] init];
    section.orientation = NSUserInterfaceLayoutOrientationVertical;
    section.alignment = NSLayoutAttributeLeading;
    section.spacing = 6;

    NSTextField *titleLabel = [self sectionLabel:title];
    [section addArrangedSubview:titleLabel];

    if (summary.length) {
        NSTextField *summaryLabel = [self detailLabel:summary];
        [section addArrangedSubview:summaryLabel];
    }

    NSStackView *rows = [[NSStackView alloc] init];
    rows.orientation = NSUserInterfaceLayoutOrientationVertical;
    rows.alignment = NSLayoutAttributeLeading;
    rows.spacing = 6;
    rows.edgeInsets = NSEdgeInsetsMake(2, 0, 0, 0);
    rows.translatesAutoresizingMaskIntoConstraints = NO;
    for (NSView *view in views) {
        [rows addArrangedSubview:view];
        view.translatesAutoresizingMaskIntoConstraints = NO;
        [view.widthAnchor constraintEqualToAnchor:rows.widthAnchor].active = YES;
    }
    [section addArrangedSubview:rows];
    [rows.widthAnchor constraintEqualToAnchor:section.widthAnchor].active = YES;
    return section;
}

- (NSStackView *)buttonGridWithButtons:(NSArray<NSButton *> *)buttons columns:(NSInteger)columns {
    NSStackView *grid = [[NSStackView alloc] init];
    grid.orientation = NSUserInterfaceLayoutOrientationVertical;
    grid.spacing = 6;
    grid.translatesAutoresizingMaskIntoConstraints = NO;
    NSInteger index = 0;
    while (index < (NSInteger)buttons.count) {
        NSStackView *row = [[NSStackView alloc] init];
        row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        row.spacing = 8;
        row.distribution = NSStackViewDistributionFillEqually;
        row.translatesAutoresizingMaskIntoConstraints = NO;
        for (NSInteger col = 0; col < columns && index < (NSInteger)buttons.count; col++, index++) {
            [row addArrangedSubview:buttons[index]];
        }
        [grid addArrangedSubview:row];
        [row.widthAnchor constraintEqualToAnchor:grid.widthAnchor].active = YES;
    }
    return grid;
}

- (NSStackView *)popupRow:(NSString *)title key:(NSString *)key titles:(NSArray<NSString *> *)titles values:(NSArray<NSString *> *)values {
    NSPopUpButton *popup = [[NSPopUpButton alloc] init];
    popup.translatesAutoresizingMaskIntoConstraints = NO;
    for (NSInteger i = 0; i < (NSInteger)titles.count; i++) {
        [popup addItemWithTitle:titles[i]];
        popup.lastItem.representedObject = i < (NSInteger)values.count ? values[i] : titles[i];
    }
    [popup.widthAnchor constraintEqualToConstant:128].active = YES;
    self.controls[key] = popup;
    return [self rowWithTitle:title control:popup];
}

- (NSStackView *)boolRow:(NSString *)title key:(NSString *)key {
    NSButton *check = [NSButton checkboxWithTitle:@"启用" target:nil action:nil];
    check.translatesAutoresizingMaskIntoConstraints = NO;
    self.controls[key] = check;
    return [self rowWithTitle:title control:check];
}

- (NSStackView *)integerRow:(NSString *)title key:(NSString *)key min:(NSInteger)min max:(NSInteger)max {
    NSTextField *field = [self numberFieldWithDecimals:0 min:min max:max];
    self.controls[key] = field;
    return [self rowWithTitle:title control:field];
}

- (NSStackView *)numberRow:(NSString *)title key:(NSString *)key min:(double)min max:(double)max decimals:(NSUInteger)decimals {
    NSTextField *field = [self numberFieldWithDecimals:decimals min:min max:max];
    self.controls[key] = field;
    return [self rowWithTitle:title control:field];
}

- (NSTextField *)numberFieldWithDecimals:(NSUInteger)decimals min:(double)min max:(double)max {
    NSTextField *field = [[NSTextField alloc] init];
    field.translatesAutoresizingMaskIntoConstraints = NO;
    [field.widthAnchor constraintEqualToConstant:96].active = YES;
    NSNumberFormatter *formatter = [[NSNumberFormatter alloc] init];
    formatter.numberStyle = NSNumberFormatterDecimalStyle;
    formatter.minimum = @(min);
    formatter.maximum = @(max);
    formatter.minimumFractionDigits = 0;
    formatter.maximumFractionDigits = decimals;
    formatter.allowsFloats = decimals > 0;
    field.formatter = formatter;
    return field;
}

- (NSDictionary *)defaultConfig {
    return @{
        @"port": @8800,
        @"rate_limit_cooldown": @60,
        @"rotation_strategy": @"most_available",
        @"product_mode": @"standard",
        @"max_retries": @10,
        @"quota_refresh_interval": @300,
        @"quota_tracker_enabled": @(YES),
        @"max_request_body_mb": @512,
        @"upstream_connect_timeout_sec": @10,
        @"upstream_transient_retries": @2,
        @"upstream_transient_backoff_ms": @250,
        @"codex_stream_mode": @"realtime",
        @"codex_hybrid_probe_seconds": @8,
        @"codex_hybrid_probe_bytes": @262144,
        @"codex_stream_retry_cooldown": @0,
        @"stream_keepalive_seconds": @15,
        @"stream_bootstrap_retries": @1,
        @"nonstream_keepalive_interval": @15,
        @"websocket_heartbeat_seconds": @0,
        @"session_affinity_enabled": @(YES),
        @"session_affinity_ttl_seconds": @3600,
        @"quota_weight_5h": @0.5,
        @"quota_weight_7d": @0.5,
        @"log_level": @"INFO",
    };
}

- (NSDictionary *)fieldTypes {
    return @{
        @"quota_weight_5h": @"float",
        @"quota_weight_7d": @"float",
        @"quota_tracker_enabled": @"bool",
        @"session_affinity_enabled": @"bool",
        @"rotation_strategy": @"string",
        @"product_mode": @"string",
        @"codex_stream_mode": @"string",
        @"log_level": @"string",
    };
}

- (NSDictionary *)fieldLabels {
    return @{
        @"port": @"代理端口",
        @"rate_limit_cooldown": @"限流冷却",
        @"rotation_strategy": @"选择策略",
        @"product_mode": @"产品模式",
        @"max_retries": @"最大重试",
        @"quota_refresh_interval": @"额度刷新间隔",
        @"quota_tracker_enabled": @"自动刷新额度",
        @"max_request_body_mb": @"请求上限 MB",
        @"upstream_connect_timeout_sec": @"连接超时",
        @"upstream_transient_retries": @"瞬时重试",
        @"upstream_transient_backoff_ms": @"退避（ms）",
        @"codex_stream_mode": @"流模式",
        @"codex_hybrid_probe_seconds": @"探测秒",
        @"codex_hybrid_probe_bytes": @"探测 bytes",
        @"codex_stream_retry_cooldown": @"流重试冷却",
        @"stream_keepalive_seconds": @"Stream keepalive",
        @"stream_bootstrap_retries": @"Bootstrap retries",
        @"nonstream_keepalive_interval": @"Nonstream keepalive",
        @"websocket_heartbeat_seconds": @"WebSocket heartbeat",
        @"session_affinity_enabled": @"Session affinity",
        @"session_affinity_ttl_seconds": @"Affinity TTL",
        @"quota_weight_5h": @"5h 权重",
        @"quota_weight_7d": @"7d 权重",
        @"log_level": @"日志级别",
    };
}

- (NSString *)labelForConfigKey:(NSString *)key {
    NSString *label = CPString([self fieldLabels][key]);
    return label.length ? label : key;
}

- (void)refresh:(id)sender {
    BOOL explicitRefresh = sender != nil;
    if (explicitRefresh) {
        self.statusLabel.stringValue = @"正在读取设置...";
    } else if (self.statusLabel) {
        self.statusLabel.stringValue = @"设置已载入，正在同步状态...";
    }
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSDictionary *config = [self fetchJSONPath:@"/api/config" method:@"GET" body:nil timeout:3.0];
        NSDictionary *status = [self.owner fetchJSONPath:@"/api/status" method:@"GET" timeout:3.0];
        NSDictionary *codex = [self.owner fetchJSONPath:@"/api/codex/proxy" method:@"GET" timeout:3.0];
        NSDictionary *menubar = [self.owner runPythonJSONSync:@[@"menubar-login-status"] rawText:nil];
        NSDictionary *ownerPayload = [self.owner snapshotPayloadRefreshingQuota:NO
                                                             quotaRefreshResult:nil
                                                                    proxyOnline:nil];
        if (!status) {
            NSString *raw = nil;
            status = [self.owner runPythonJSONSync:@[@"status"] rawText:&raw];
        }
        if (!config) {
            config = CPDict(status[@"config"]);
        }
        if (!codex) {
            codex = @{
                @"enabled": status[@"enabled"] ?: @(NO),
                @"mode": status[@"mode"] ?: @"",
                @"expected": @{
                    @"codex_base_url": status[@"codex_expected_base_url"] ?: @"",
                },
            };
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            [self.owner applySnapshotPayload:ownerPayload ?: @{}];
            if (config.count) {
                self.configSnapshot = config;
            } else if (!self.configSnapshot.count) {
                self.configSnapshot = [self defaultConfig];
            }
            self.statusSnapshot = status ?: self.statusSnapshot ?: @{};
            self.codexSnapshot = codex ?: @{};
            self.menubarLoginSnapshot = menubar ?: @{};
            NSInteger selected = self.selectedSettingsIndex;
            [self rebuildSettingsPagesSelectingIndex:selected];
            [self populateControls];
            [self renderSettingsSectionAtIndex:selected];
            [self scrollAllTabsToTopAfterLayout];
            self.statusLabel.stringValue = @"设置已读取";
            [self auditButtonsInWindow:self.window context:@"settings-refresh"];
        });
    });
}

- (void)scrollAllTabsToTop {
    for (NSScrollView *scroll in self.scrollViews) {
        [self scrollViewToTop:scroll];
    }
}

- (void)scrollAllTabsToTopAfterLayout {
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.window.contentView layoutSubtreeIfNeeded];
        [self scrollAllTabsToTop];
    });
}

- (void)scrollViewToTop:(NSScrollView *)scroll {
    [scroll.documentView layoutSubtreeIfNeeded];
    NSClipView *clip = scroll.contentView;
    [clip scrollToPoint:NSMakePoint(0, 0)];
    [scroll reflectScrolledClipView:clip];
}

- (void)populateControls {
    NSDictionary *config = self.configSnapshot.count ? self.configSnapshot : [self defaultConfig];
    for (NSString *key in self.controls) {
        NSControl *control = self.controls[key];
        id value = config[key] ?: [self defaultConfig][key];
        if ([control isKindOfClass:NSPopUpButton.class]) {
            NSPopUpButton *popup = (NSPopUpButton *)control;
            NSInteger targetIndex = -1;
            for (NSInteger i = 0; i < (NSInteger)popup.numberOfItems; i++) {
                if ([CPString([popup itemAtIndex:i].representedObject) isEqualToString:CPString(value)]) {
                    targetIndex = i;
                    break;
                }
            }
            if (targetIndex >= 0) {
                [popup selectItemAtIndex:targetIndex];
            }
        } else if ([control isKindOfClass:NSButton.class]) {
            ((NSButton *)control).state = CPBool(value) ? NSControlStateValueOn : NSControlStateValueOff;
        } else if ([control isKindOfClass:NSTextField.class]) {
            ((NSTextField *)control).doubleValue = CPDouble(value);
        }
    }

    BOOL proxyEnabled = CPBool(self.codexSnapshot[@"enabled"]) || CPBool(self.statusSnapshot[@"enabled"]);
    self.proxyModeControl.selectedSegment = proxyEnabled ? 0 : 1;
    NSString *mode = CPString(self.codexSnapshot[@"mode"]);
    if (!mode.length) {
        mode = CPString(self.statusSnapshot[@"mode"]);
    }
    self.codexLabel.stringValue = [NSString stringWithFormat:@"当前：%@ · %@",
                                   proxyEnabled ? @"账号池代理" : @"直连",
                                   mode.length ? mode : @"unknown"];
    NSDictionary *expected = CPDict(self.codexSnapshot[@"expected"]);
    NSString *base = CPString(expected[@"codex_base_url"]);
    if (!base.length) {
        base = CPString(self.statusSnapshot[@"codex_expected_base_url"]);
    }
    self.baseURLLabel.stringValue = [NSString stringWithFormat:@"预期 base URL：%@", base.length ? base : @"-"];
    self.codexModeSummaryLabel.stringValue = proxyEnabled ? @"账号池代理" : @"直连";
    self.codexBaseSummaryLabel.stringValue = base.length ? base : @"-";

    BOOL running = CPBool(self.statusSnapshot[@"running"]);
    self.serviceLabel.stringValue = [NSString stringWithFormat:@"后台：%@ · 可用账号 %@/%@ · 版本 %@",
                                     running ? @"在线" : @"离线",
                                     CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                                     CPDisplayString(self.statusSnapshot[@"total_accounts"]),
                                     CPDisplayString(self.statusSnapshot[@"proxy_version"])];
    self.summaryStatusLabel.stringValue = running ? @"在线" : @"离线";
    self.summaryAccountsLabel.stringValue = [NSString stringWithFormat:@"%@/%@",
                                             CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                                             CPDisplayString(self.statusSnapshot[@"total_accounts"])];
    self.summaryVersionLabel.stringValue = CPDisplayString(self.statusSnapshot[@"proxy_version"]);
    self.summaryStatusLabel.textColor = running ? NSColor.systemGreenColor : NSColor.systemOrangeColor;
    NSInteger errorCount = CPArray(self.statusSnapshot[@"recent_errors"]).count;
    BOOL repairNeeded = CPBool(self.statusSnapshot[@"needs_repair"]) || CPBool(self.statusSnapshot[@"version_mismatch"]) || [self.owner hasRuntimeManifestMismatch] || [self.owner hasUsageStorageMismatch];
    NSDictionary *tracker = CPDict(self.statusSnapshot[@"quota_tracker"]);
    BOOL quotaEnabled = CPBool(tracker[@"enabled"]);
    BOOL quotaRunning = CPBool(tracker[@"running"]);
    NSString *quotaText = @"等待额度刷新";
    if (tracker.count) {
        NSString *lastRun = CPRelativeTime(tracker[@"last_run_at"]);
        NSInteger interval = MAX(0, (NSInteger)CPDouble(tracker[@"interval"]));
        NSString *intervalText = interval >= 60
            ? [NSString stringWithFormat:@"%ld 分钟", (long)MAX(1, interval / 60)]
            : [NSString stringWithFormat:@"%ld 秒", (long)interval];
        quotaText = quotaEnabled
            ? [NSString stringWithFormat:@"%@ · 上次 %@", quotaRunning ? intervalText : @"待启动", lastRun]
            : @"自动刷新关闭";
    }
    self.overviewFocusServiceLabel.stringValue = running ? @"在线，正在接管本机请求" : @"离线，先启动/修复";
    self.overviewFocusServiceLabel.textColor = running ? NSColor.systemGreenColor : NSColor.systemOrangeColor;
    self.overviewFocusAccountsLabel.stringValue = [NSString stringWithFormat:@"%@/%@ 可用",
                                                   CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                                                   CPDisplayString(self.statusSnapshot[@"total_accounts"])];
    self.overviewFocusAccountsLabel.textColor = CPDouble(self.statusSnapshot[@"active_accounts"]) > 0 ? NSColor.labelColor : NSColor.systemOrangeColor;
    self.overviewFocusRepairLabel.stringValue = repairNeeded ? @"需要处理，见诊断页" : @"无待处理修复";
    self.overviewFocusRepairLabel.textColor = repairNeeded ? NSColor.systemOrangeColor : NSColor.systemGreenColor;
    self.overviewFocusErrorsLabel.stringValue = errorCount ? [NSString stringWithFormat:@"%ld 条最近错误", (long)errorCount] : @"暂无最近错误";
    self.overviewFocusErrorsLabel.textColor = errorCount ? NSColor.systemOrangeColor : NSColor.systemGreenColor;
    self.overviewFocusQuotaLabel.stringValue = quotaText;
    self.overviewFocusQuotaLabel.textColor = quotaEnabled ? NSColor.labelColor : NSColor.systemOrangeColor;
    self.sidebarStatusLabel.stringValue = running ? @"在线" : @"离线";
    self.sidebarStatusLabel.textColor = running ? NSColor.systemGreenColor : NSColor.systemOrangeColor;
    self.sidebarAccountsLabel.stringValue = [NSString stringWithFormat:@"账号 %@/%@",
                                             CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                                             CPDisplayString(self.statusSnapshot[@"total_accounts"])];
    self.sidebarVersionLabel.stringValue = [NSString stringWithFormat:@"版本 %@",
                                            CPDisplayString(self.statusSnapshot[@"proxy_version"])];

    self.runtimeDirLabel.stringValue = CPDisplayString(self.statusSnapshot[@"runtime_dir"]);
    self.sourceDirLabel.stringValue = CPDisplayString(self.statusSnapshot[@"source_dir"]);
    self.frontendVersionLabel.stringValue = CPDisplayString(self.owner.frontendVersion);
    self.runtimeVersionLabel.stringValue = CPDisplayString(self.statusSnapshot[@"runtime_version"]);
    self.proxyVersionLabel.stringValue = CPDisplayString(self.statusSnapshot[@"proxy_version"]);
    self.manifestLabel.stringValue = CPBool(self.statusSnapshot[@"manifest_ok"]) ? @"一致" : CPDisplayString(self.statusSnapshot[@"manifest_error"]);
    self.manifestLabel.textColor = CPBool(self.statusSnapshot[@"manifest_ok"]) ? NSColor.systemGreenColor : NSColor.systemOrangeColor;

    NSString *strategy = CPString(config[@"rotation_strategy"]);
    if (!strategy.length) {
        strategy = CPString(self.statusSnapshot[@"strategy"]);
    }
    self.routingCurrentStrategyLabel.stringValue = [self.owner strategyTitleForValue:strategy.length ? strategy : @"most_available"];
    NSInteger cooldownCount = 0;
    for (NSDictionary *account in self.owner.accounts ?: @[]) {
        if (CPBool(account[@"rate_limited"])) {
            cooldownCount += 1;
        }
    }
    self.routingCooldownLabel.stringValue = cooldownCount ? [NSString stringWithFormat:@"%ld 个账号冷却中", (long)cooldownCount] : @"无账号冷却";
    self.routingCooldownLabel.textColor = cooldownCount ? NSColor.systemOrangeColor : NSColor.systemGreenColor;
    self.routingRefreshLabel.stringValue = quotaText;
    self.routingRefreshLabel.textColor = quotaEnabled ? NSColor.labelColor : NSColor.systemOrangeColor;
    self.routingWindowLabel.stringValue = [NSString stringWithFormat:@"5h %.2f / 7d %.2f",
                                           CPDouble(config[@"quota_weight_5h"]),
                                           CPDouble(config[@"quota_weight_7d"])];

    NSString *port = CPDisplayString(config[@"port"]);
    if ([port isEqualToString:@"-"]) {
        port = @"8800";
    }
    NSString *openAIBase = base.length ? base : [NSString stringWithFormat:@"http://127.0.0.1:%@/v1", port];
    NSString *chatGPTBase = [NSString stringWithFormat:@"http://127.0.0.1:%@/backend-api/", port];
    self.codexOpenAIBaseLabel.stringValue = openAIBase;
    self.codexChatGPTBaseLabel.stringValue = chatGPTBase;
    self.codexPortLabel.stringValue = [NSString stringWithFormat:@"%@ · %@", port, running ? @"后台在线" : @"后台离线"];
    self.codexPortLabel.textColor = running ? NSColor.labelColor : NSColor.systemOrangeColor;
    self.codexRestartLabel.stringValue = repairNeeded ? @"建议修复/重启后确认" : @"当前无需重启";
    self.codexRestartLabel.textColor = repairNeeded ? NSColor.systemOrangeColor : NSColor.systemGreenColor;

    self.advancedRestartImpactLabel.stringValue = [NSString stringWithFormat:@"端口 %@、请求体上限和上游网络项保存后以后台状态为准", port];
    self.advancedStreamImpactLabel.stringValue = [NSString stringWithFormat:@"%@ · keepalive %@s",
                                                  CPDisplayString(config[@"codex_stream_mode"]),
                                                  CPDisplayString(config[@"stream_keepalive_seconds"])];
    self.advancedSessionImpactLabel.stringValue = CPBool(config[@"session_affinity_enabled"])
        ? [NSString stringWithFormat:@"开启 · TTL %@s", CPDisplayString(config[@"session_affinity_ttl_seconds"])]
        : @"关闭，会按策略重新选择账号";
    self.advancedSaveImpactLabel.stringValue = running ? @"保存后尝试热应用" : @"后台离线时写入本地配置";
    self.advancedSaveImpactLabel.textColor = running ? NSColor.labelColor : NSColor.systemOrangeColor;
    if (self.menuBarLoginItemControl) {
        BOOL menubarEnabled = CPBool(self.menubarLoginSnapshot[@"enabled"]);
        self.menuBarLoginItemControl.state = menubarEnabled ? NSControlStateValueOn : NSControlStateValueOff;
    }
    if (self.menuBarLoginItemLabel) {
        BOOL menubarEnabled = CPBool(self.menubarLoginSnapshot[@"enabled"]);
        NSString *plist = CPString(self.menubarLoginSnapshot[@"plist_path"]);
        self.menuBarLoginItemLabel.stringValue = menubarEnabled
            ? @"已开启；登录后会常驻菜单栏，不主动弹出控制中心"
            : (plist.length ? @"未开启；登录后不会自动显示菜单栏入口" : @"未开启");
        self.menuBarLoginItemLabel.textColor = menubarEnabled ? NSColor.labelColor : NSColor.secondaryLabelColor;
    }
}

- (NSDictionary *)configFromControlsWithError:(NSString **)errorMessage {
    NSMutableDictionary *updates = [NSMutableDictionary dictionary];
    NSDictionary *types = [self fieldTypes];
    for (NSString *key in self.controls) {
        NSControl *control = self.controls[key];
        NSString *type = CPString(types[key]);
        if ([control isKindOfClass:NSPopUpButton.class]) {
            updates[key] = CPDisplayString(((NSPopUpButton *)control).selectedItem.representedObject);
        } else if ([control isKindOfClass:NSButton.class] || [type isEqualToString:@"bool"]) {
            updates[key] = CPJSONBool(((NSButton *)control).state == NSControlStateValueOn);
        } else if ([type isEqualToString:@"float"]) {
            NSTextField *field = (NSTextField *)control;
            NSString *raw = [field.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
            NSNumberFormatter *formatter = [field.formatter isKindOfClass:NSNumberFormatter.class] ? (NSNumberFormatter *)field.formatter : nil;
            NSNumber *number = raw.length ? [formatter numberFromString:raw] : nil;
            if (!number) {
                if (errorMessage) {
                    *errorMessage = [NSString stringWithFormat:@"%@ 必须填写数字。", [self labelForConfigKey:key]];
                }
                return nil;
            }
            double value = number.doubleValue;
            if ((formatter.minimum && value < formatter.minimum.doubleValue) || (formatter.maximum && value > formatter.maximum.doubleValue)) {
                if (errorMessage) {
                    *errorMessage = [NSString stringWithFormat:@"%@ 必须在 %.3g 到 %.3g 之间。", [self labelForConfigKey:key], formatter.minimum.doubleValue, formatter.maximum.doubleValue];
                }
                return nil;
            }
            updates[key] = @(value);
        } else {
            NSTextField *field = (NSTextField *)control;
            NSString *raw = [field.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
            NSNumberFormatter *formatter = [field.formatter isKindOfClass:NSNumberFormatter.class] ? (NSNumberFormatter *)field.formatter : nil;
            NSNumber *number = raw.length ? [formatter numberFromString:raw] : nil;
            if (!number) {
                if (errorMessage) {
                    *errorMessage = [NSString stringWithFormat:@"%@ 必须填写整数。", [self labelForConfigKey:key]];
                }
                return nil;
            }
            double value = number.doubleValue;
            double rounded = round(value);
            if (fabs(value - rounded) > 0.000001) {
                if (errorMessage) {
                    *errorMessage = [NSString stringWithFormat:@"%@ 必须是整数。", [self labelForConfigKey:key]];
                }
                return nil;
            }
            if ((formatter.minimum && value < formatter.minimum.doubleValue) || (formatter.maximum && value > formatter.maximum.doubleValue)) {
                if (errorMessage) {
                    *errorMessage = [NSString stringWithFormat:@"%@ 必须在 %.0f 到 %.0f 之间。", [self labelForConfigKey:key], formatter.minimum.doubleValue, formatter.maximum.doubleValue];
                }
                return nil;
            }
            updates[key] = @((NSInteger)llround(value));
        }
    }
    if (updates[@"quota_tracker_enabled"]) {
        updates[@"quota_tracker_user_set"] = CPJSONBool(YES);
    }
    if (updates[@"codex_stream_mode"]) {
        updates[@"codex_stream_mode_user_set"] = CPJSONBool(YES);
    }
    if (updates[@"quota_weight_5h"] && updates[@"quota_weight_7d"] && CPDouble(updates[@"quota_weight_5h"]) + CPDouble(updates[@"quota_weight_7d"]) <= 0) {
        if (errorMessage) {
            *errorMessage = @"5h 权重和 7d 权重不能同时为 0。";
        }
        return nil;
    }
    return updates;
}

- (void)save:(id)sender {
    NSString *validationError = nil;
    NSDictionary *updates = [self configFromControlsWithError:&validationError];
    if (!updates) {
        self.statusLabel.stringValue = [NSString stringWithFormat:@"保存失败：%@", validationError ?: @"配置输入无效"];
        [self.owner appendLog:[NSString stringWithFormat:@"设置保存失败\n%@", validationError ?: @"配置输入无效"]];
        return;
    }
    BOOL canChangeProxyMode = self.selectedSettingsIndex == 3 && self.proxyModeControl != nil;
    BOOL desiredProxy = canChangeProxyMode ? self.proxyModeControl.selectedSegment != 1 : NO;
    BOOL currentProxy = CPBool(self.codexSnapshot[@"enabled"]) || CPBool(self.statusSnapshot[@"enabled"]);
    BOOL canChangeMenuBarLogin = self.selectedSettingsIndex == 4 && self.menuBarLoginItemControl != nil;
    BOOL desiredMenuBarLogin = canChangeMenuBarLogin ? self.menuBarLoginItemControl.state == NSControlStateValueOn : NO;
    BOOL currentMenuBarLogin = CPBool(self.menubarLoginSnapshot[@"enabled"]);
    self.statusLabel.stringValue = @"正在保存设置...";
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *jsonError = nil;
        NSData *jsonData = [NSJSONSerialization dataWithJSONObject:updates options:0 error:&jsonError];
        NSString *json = jsonData ? [[NSString alloc] initWithData:jsonData encoding:NSUTF8StringEncoding] : @"{}";
        NSDictionary *result = nil;
        if (!jsonError) {
            result = [self fetchJSONPath:@"/api/config" method:@"PUT" body:jsonData timeout:5.0];
        }
        if (!result || result[@"error"]) {
            NSString *raw = nil;
            result = [self.owner runPythonJSONSync:@[@"set-config", @"--config-json", json ?: @"{}"] rawText:&raw];
        }

        NSDictionary *proxyResult = nil;
        if (canChangeProxyMode && desiredProxy != currentProxy) {
            NSData *proxyBody = [NSJSONSerialization dataWithJSONObject:@{@"enabled": CPJSONBool(desiredProxy)} options:0 error:nil];
            proxyResult = [self fetchJSONPath:@"/api/codex/proxy" method:@"PUT" body:proxyBody timeout:5.0];
            if (!proxyResult || proxyResult[@"error"]) {
                NSString *raw = nil;
                proxyResult = [self.owner runPythonJSONSync:@[desiredProxy ? @"enable-codex-proxy" : @"disable-codex-proxy"] rawText:&raw];
            }
        }

        NSDictionary *menubarResult = nil;
        if (canChangeMenuBarLogin && desiredMenuBarLogin != currentMenuBarLogin) {
            NSString *raw = nil;
            menubarResult = [self.owner runPythonJSONSync:@[desiredMenuBarLogin ? @"enable-menubar-login" : @"disable-menubar-login"] rawText:&raw];
        }

        dispatch_async(dispatch_get_main_queue(), ^{
            NSString *errorText = CPString(result[@"error"]);
            if (errorText.length) {
                self.statusLabel.stringValue = [NSString stringWithFormat:@"保存失败：%@", errorText];
                [self.owner appendLog:[NSString stringWithFormat:@"设置保存失败\n%@", CPPrettyJSON(result)]];
                return;
            }
            BOOL restartRequired = CPBool(result[@"restart_required"]);
            NSString *proxyError = CPString(proxyResult[@"error"]);
            NSString *menubarError = CPString(menubarResult[@"error"]);
            if (proxyError.length) {
                self.statusLabel.stringValue = [NSString stringWithFormat:@"设置已保存，代理模式切换失败：%@", proxyError];
            } else if (menubarError.length) {
                self.statusLabel.stringValue = [NSString stringWithFormat:@"设置已保存，菜单栏常驻切换失败：%@", menubarError];
            } else {
                self.statusLabel.stringValue = restartRequired ? @"设置已保存；端口变更需要重启后台生效" : @"设置已保存";
            }
            [self.owner appendLog:[NSString stringWithFormat:@"设置保存\n%@\n%@\n%@", CPPrettyJSON(result), proxyResult ? CPPrettyJSON(proxyResult) : @"", menubarResult ? CPPrettyJSON(menubarResult) : @""]];
            [self.owner refreshSnapshots:nil];
            [self refresh:nil];
        });
    });
}

- (void)restoreDefaults:(id)sender {
    self.configSnapshot = [self defaultConfig];
    [self populateControls];
    self.statusLabel.stringValue = @"已填入默认值，点击“保存设置”后生效";
}

- (NSDictionary *)fetchJSONPath:(NSString *)path method:(NSString *)method body:(NSData *)body timeout:(NSTimeInterval)timeout {
    NSString *urlString = [@"http://127.0.0.1:8800" stringByAppendingString:path];
    NSURL *url = [NSURL URLWithString:urlString];
    if (!url) {
        return nil;
    }
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:timeout];
    request.HTTPMethod = method ?: @"GET";
    if (body) {
        request.HTTPBody = body;
        [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    } else if (![request.HTTPMethod isEqualToString:@"GET"]) {
        request.HTTPBody = [NSData data];
    }

    dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
    __block NSData *responseData = nil;
    NSURLSessionDataTask *task = [NSURLSession.sharedSession dataTaskWithRequest:request
                                                               completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSHTTPURLResponse *http = [response isKindOfClass:NSHTTPURLResponse.class] ? (NSHTTPURLResponse *)response : nil;
        if (!error && http.statusCode >= 200 && http.statusCode < 500) {
            responseData = data;
        }
        dispatch_semaphore_signal(semaphore);
    }];
    [task resume];
    dispatch_semaphore_wait(semaphore, dispatch_time(DISPATCH_TIME_NOW, (int64_t)((timeout + 1.0) * NSEC_PER_SEC)));
    if (!responseData) {
        [task cancel];
        return nil;
    }
    id parsed = [NSJSONSerialization JSONObjectWithData:responseData options:0 error:nil];
    return [parsed isKindOfClass:NSDictionary.class] ? parsed : nil;
}

- (void)auditButtonsInWindow:(NSWindow *)window context:(NSString *)context {
    NSMutableArray<NSButton *> *buttons = [NSMutableArray array];
    [self collectButtonsFromView:window.contentView into:buttons];
    NSMutableArray<NSString *> *issues = [NSMutableArray array];
    for (NSInteger i = 0; i < (NSInteger)buttons.count; i++) {
        NSButton *a = buttons[i];
        if (a.hidden || a.alphaValue <= 0.01) {
            continue;
        }
        NSRect af = [a.superview convertRect:a.frame toView:nil];
        CGFloat needed = a.intrinsicContentSize.width;
        if (needed > 0 && af.size.width > 0 && needed > af.size.width + 3) {
            [issues addObject:[NSString stringWithFormat:@"裁切：%@ need %.0f > %.0f", a.title, needed, af.size.width]];
        }
        for (NSInteger j = i + 1; j < (NSInteger)buttons.count; j++) {
            NSButton *b = buttons[j];
            if (b.hidden || b.alphaValue <= 0.01) {
                continue;
            }
            NSRect bf = [b.superview convertRect:b.frame toView:nil];
            NSRect inter = NSIntersectionRect(af, bf);
            if (!NSIsEmptyRect(inter) && inter.size.width * inter.size.height > 4) {
                [issues addObject:[NSString stringWithFormat:@"重叠：%@ / %@", a.title, b.title]];
            }
        }
    }
    if (issues.count) {
        [self.owner appendLog:[NSString stringWithFormat:@"布局巡检 %@\n%@", context, [issues componentsJoinedByString:@"\n"]]];
    }
}

- (void)collectButtonsFromView:(NSView *)view into:(NSMutableArray<NSButton *> *)buttons {
    if (view.hidden || view.alphaValue <= 0.01) {
        return;
    }
    if ([view isKindOfClass:NSButton.class]) {
        [buttons addObject:(NSButton *)view];
    }
    for (NSView *subview in view.subviews) {
        [self collectButtonsFromView:subview into:buttons];
    }
}

@end

@interface AppDelegate : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) ControlWindowController *controller;
@property(nonatomic, strong) NSStatusItem *statusItem;
@property(nonatomic, strong) NSMenu *statusMenu;
@property(nonatomic, strong) NSMenuItem *statusMenuItem;
@property(nonatomic, strong) NSMenuItem *quota5hMenuItem;
@property(nonatomic, strong) NSMenuItem *quota7dMenuItem;
@property(nonatomic, strong) NSTimer *statusRefreshTimer;
@property(nonatomic, assign) BOOL launchAsMenuBarOnly;
@end

@implementation AppDelegate
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.controller = [[ControlWindowController alloc] init];
    [self installMainMenu];
    [self installStatusItem];
    [self.controller startHeadlessRuntimeInitializationWithCompletion:^(BOOL ok) {
        [self refreshMenuStatus:nil];
    }];
    self.statusRefreshTimer = [NSTimer scheduledTimerWithTimeInterval:30
                                                               target:self
                                                             selector:@selector(refreshMenuStatus:)
                                                             userInfo:nil
                                                              repeats:YES];
    if (!self.launchAsMenuBarOnly) {
        [self openControlCenter:nil];
    }
}

- (void)installStatusItem {
    self.statusItem = [NSStatusBar.systemStatusBar statusItemWithLength:NSSquareStatusItemLength];
    NSStatusBarButton *button = self.statusItem.button;
    button.image = CPMenuBarIconImage();
    if (button.image) {
        button.title = @"";
        button.imagePosition = NSImageOnly;
    } else {
        button.title = @"腊";
        button.imagePosition = NSNoImage;
    }
    button.toolTip = @"小腊肠控制中心";
    button.target = self;
    button.action = @selector(showStatusMenu:);

    NSMenu *menu = [[NSMenu alloc] initWithTitle:@"小腊肠"];
    self.statusMenuItem = [[NSMenuItem alloc] initWithTitle:@"读取中 · -/- 账号" action:nil keyEquivalent:@""];
    self.statusMenuItem.enabled = NO;
    [menu addItem:self.statusMenuItem];
    self.quota5hMenuItem = [[NSMenuItem alloc] initWithTitle:@"5h 剩余 额度待刷新" action:nil keyEquivalent:@""];
    self.quota5hMenuItem.enabled = NO;
    [menu addItem:self.quota5hMenuItem];
    self.quota7dMenuItem = [[NSMenuItem alloc] initWithTitle:@"7d 剩余 额度待刷新" action:nil keyEquivalent:@""];
    self.quota7dMenuItem.enabled = NO;
    [menu addItem:self.quota7dMenuItem];
    [menu addItem:[NSMenuItem separatorItem]];

    NSMenuItem *open = [[NSMenuItem alloc] initWithTitle:@"控制中心"
                                                  action:@selector(openControlCenter:)
                                           keyEquivalent:@""];
    open.target = self;
    [menu addItem:open];

    NSMenuItem *refresh = [[NSMenuItem alloc] initWithTitle:@"刷新状态"
                                                     action:@selector(refreshMenuStatus:)
                                              keyEquivalent:@"r"];
    refresh.target = self;
    [menu addItem:refresh];

    [menu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *quit = [[NSMenuItem alloc] initWithTitle:@"退出小腊肠"
                                                  action:@selector(terminate:)
                                           keyEquivalent:@"q"];
    quit.target = NSApp;
    [menu addItem:quit];
    self.statusMenu = menu;
}

- (void)showStatusMenu:(id)sender {
    if (!self.statusMenu) {
        return;
    }
    [self refreshMenuStatus:nil];
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    [self.statusItem popUpStatusItemMenu:self.statusMenu];
#pragma clang diagnostic pop
}

- (void)openControlCenter:(id)sender {
    [self.controller showSettings:sender];
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    [self openControlCenter:nil];
    return YES;
}

- (NSString *)quotaMenuTitleForWeekly:(BOOL)weekly {
    NSString *prefix = weekly ? @"7d" : @"5h";
    NSDictionary *summary = [self.controller quotaSummary];
    NSInteger accounts = (NSInteger)CPDouble(summary[@"accounts"]);
    NSInteger unknown = (NSInteger)CPDouble(summary[@"unknown"]);
    if (accounts <= 0 || unknown >= accounts) {
        return [NSString stringWithFormat:@"%@ 剩余 额度待刷新", prefix];
    }
    NSString *total = [self.controller quotaTotalTextForWeekly:weekly];
    if (unknown > 0) {
        return [NSString stringWithFormat:@"%@ 剩余 %@ · %@ 个待刷新", prefix, total, @(unknown)];
    }
    return [NSString stringWithFormat:@"%@ 剩余 %@", prefix, total];
}

- (void)refreshMenuStatus:(id)sender {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        BOOL proxyOnline = NO;
        NSDictionary *payload = [self.controller snapshotPayloadRefreshingQuota:NO
                                                              quotaRefreshResult:nil
                                                                     proxyOnline:&proxyOnline];
        dispatch_async(dispatch_get_main_queue(), ^{
            [self.controller applySilentSnapshotPayload:payload ?: @{}];
            BOOL running = CPBool(self.controller.statusSnapshot[@"running"]) || proxyOnline;
            NSString *state = running ? @"在线" : @"离线";
            NSString *active = CPDisplayString(self.controller.statusSnapshot[@"active_accounts"]);
            NSString *total = CPDisplayString(self.controller.statusSnapshot[@"total_accounts"]);
            self.statusMenuItem.title = [NSString stringWithFormat:@"%@ · %@/%@ 账号", state, active, total];
            self.quota5hMenuItem.title = [self quotaMenuTitleForWeekly:NO];
            self.quota7dMenuItem.title = [self quotaMenuTitleForWeekly:YES];
        });
    });
}

- (void)installMainMenu {
    NSString *appName = CPDisplayString(NSBundle.mainBundle.infoDictionary[@"CFBundleName"]);
    NSMenu *mainMenu = [[NSMenu alloc] initWithTitle:@""];
    NSMenuItem *appItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:appItem];

    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:appName];
    NSMenuItem *settings = [[NSMenuItem alloc] initWithTitle:@"设置..."
                                                      action:@selector(showSettings:)
                                               keyEquivalent:@","];
    settings.target = self.controller;
    [appMenu addItem:settings];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:[NSString stringWithFormat:@"隐藏 %@", appName]
                       action:@selector(hide:)
                keyEquivalent:@"h"];
    NSMenuItem *hideOthers = [[NSMenuItem alloc] initWithTitle:@"隐藏其他"
                                                        action:@selector(hideOtherApplications:)
                                                 keyEquivalent:@"h"];
    hideOthers.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagOption;
    [appMenu addItem:hideOthers];
    [appMenu addItemWithTitle:@"全部显示" action:@selector(unhideAllApplications:) keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:[NSString stringWithFormat:@"退出 %@", appName]
                       action:@selector(terminate:)
                keyEquivalent:@"q"];
    appItem.submenu = appMenu;
    NSApp.mainMenu = mainMenu;
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return NO;
}
@end

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        BOOL menuBarOnly = NO;
        for (int i = 1; i < argc; i++) {
            if (strcmp(argv[i], "--menubar-only") == 0) {
                menuBarOnly = YES;
            }
        }
        NSApplication *app = NSApplication.sharedApplication;
        AppDelegate *delegate = [[AppDelegate alloc] init];
        delegate.launchAsMenuBarOnly = menuBarOnly;
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [app run];
    }
    return 0;
}
