#import <Cocoa/Cocoa.h>

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

@interface ControlWindowController : NSObject <NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate>
@property(nonatomic, strong) NSWindow *window;
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
@property(nonatomic, strong) NSArray<NSDictionary *> *accounts;
@property(nonatomic, strong) NSDictionary *statusSnapshot;
@property(nonatomic, strong) NSDictionary *quotaSnapshot;
@property(nonatomic, copy) NSString *activeSection;
@property(nonatomic, copy) NSString *selectedAccountName;
@property(nonatomic, copy) NSString *appBundlePath;
@property(nonatomic, copy) NSString *resourceRuntimeDir;
@property(nonatomic, copy) NSString *runtimeDir;
@property(nonatomic, copy) NSString *resultPath;
@property(nonatomic, copy) NSString *logPath;
@property(nonatomic, strong) NSTimer *refreshTimer;
@property(nonatomic, assign) BOOL busy;
@property(nonatomic, assign) BOOL compactInspector;
@end

@interface CPFlippedStackView : NSStackView
@end

@implementation CPFlippedStackView
- (BOOL)isFlipped {
    return YES;
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
    _resourceRuntimeDir = [bundle.resourceURL URLByAppendingPathComponent:@"runtime"].path;
    _runtimeDir = [@"~/Library/Application Support/codexproxyapi" stringByExpandingTildeInPath];
    _resultPath = [_runtimeDir stringByAppendingPathComponent:@"control-result.txt"];
    _logPath = [_runtimeDir stringByAppendingPathComponent:@"control-app.log"];
    _buttons = [NSMutableArray array];
    _navButtons = [NSMutableArray array];
    _accounts = @[];
    _statusSnapshot = @{};
    _quotaSnapshot = @{};
    _activeSection = @"dashboard";
    return self;
}

- (void)show {
    NSRect frame = NSMakeRect(0, 0, 600, 460);
    self.window = [[NSWindow alloc] initWithContentRect:frame
                                             styleMask:(NSWindowStyleMaskTitled |
                                                        NSWindowStyleMaskClosable |
                                                        NSWindowStyleMaskMiniaturizable)
                                               backing:NSBackingStoreBuffered
                                                 defer:NO];
    self.window.title = @"Codex 代理控制台";
    self.window.contentMinSize = NSMakeSize(600, 460);
    self.window.contentMaxSize = NSMakeSize(600, 460);
    self.window.minSize = self.window.frame.size;
    self.window.maxSize = self.window.frame.size;
    self.window.delegate = self;
    self.window.titlebarAppearsTransparent = NO;
    self.window.movableByWindowBackground = NO;
    [self.window center];

    NSView *root = [[NSView alloc] initWithFrame:frame];
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    root.wantsLayer = YES;
    root.layer.backgroundColor = NSColor.windowBackgroundColor.CGColor;
    self.window.contentView = root;

    NSView *sidebar = [[NSView alloc] init];
    sidebar.wantsLayer = YES;
    sidebar.layer.backgroundColor = NSColor.controlBackgroundColor.CGColor;
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
    [NSApp activateIgnoringOtherApps:YES];
    [self appendLog:@"控制台已启动。原生 App 会优先读取本地代理 API，代理离线时回退到本地账号扫描。"];
    [self startRuntimeInitialization];
    self.refreshTimer = [NSTimer scheduledTimerWithTimeInterval:15
                                                         target:self
                                                       selector:@selector(refreshSnapshots:)
                                                       userInfo:nil
                                                        repeats:YES];
}

- (void)startRuntimeInitialization {
    self.footerStatusLabel.stringValue = @"正在准备运行目录...";
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *error = nil;
        BOOL ok = [self ensureRuntimeReady:&error];
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!ok) {
                [self appendLog:[NSString stringWithFormat:@"运行目录初始化失败：%@", error.localizedDescription]];
                self.footerStatusLabel.stringValue = @"运行目录初始化失败";
                return;
            }
            [self appendLog:@"运行目录已就绪。"];
            [self refreshSnapshots:nil];
        });
    });
}

- (void)windowWillClose:(NSNotification *)notification {
    [self.refreshTimer invalidate];
    self.refreshTimer = nil;
}

#pragma mark - Layout

- (void)buildSidebarInView:(NSView *)sidebar {
    self.sidebarStack = [[NSStackView alloc] init];
    self.sidebarStack.orientation = NSUserInterfaceLayoutOrientationVertical;
    self.sidebarStack.alignment = NSLayoutAttributeLeading;
    self.sidebarStack.spacing = 6;
    self.sidebarStack.edgeInsets = NSEdgeInsetsMake(16, 8, 10, 8);
    self.sidebarStack.translatesAutoresizingMaskIntoConstraints = NO;
    [sidebar addSubview:self.sidebarStack];
    [self pinView:self.sidebarStack toView:sidebar insets:NSEdgeInsetsMake(16, 8, 12, 8)];

    [self.sidebarStack addArrangedSubview:[self sidebarBrandIconView]];
    [self addSpacerToStack:self.sidebarStack height:10];

    NSArray<NSDictionary *> *items = @[
        @{@"id": @"dashboard", @"title": @"总览", @"symbol": @"gauge"},
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

    NSView *statusCard = [self cardView];
    statusCard.translatesAutoresizingMaskIntoConstraints = NO;
    [statusCard.widthAnchor constraintEqualToConstant:102].active = YES;
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
    [self.toolbarStack addArrangedSubview:[self actionButtonWithTitle:@"启动/修复" symbol:@"play.circle.fill" selector:@selector(repairAction:) primary:YES]];
    [self.toolbarStack addArrangedSubview:[self actionButtonWithTitle:@"打开 Web" symbol:@"safari" selector:@selector(openWebAction:) primary:NO]];
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

    [self addDividerToStack:rootStack top:8 bottom:8];

    NSScrollView *scroll = [[NSScrollView alloc] init];
    scroll.drawsBackground = NO;
    scroll.hasVerticalScroller = YES;
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

    self.footerStatusLabel = [self labelWithText:@"就绪" font:[NSFont systemFontOfSize:11 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
    [self.footerStatusLabel setContentCompressionResistancePriority:NSLayoutPriorityRequired forOrientation:NSLayoutConstraintOrientationVertical];
    [rootStack addArrangedSubview:self.footerStatusLabel];

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

    if ([self.activeSection isEqualToString:@"config"]) {
        [self renderConfigSection];
    } else if ([self.activeSection isEqualToString:@"logs"]) {
        [self renderLogsSection];
    } else {
        [self renderDashboardSection];
    }
    [self reloadAccountTableSelection];
    [self updateHeaderText];
}

- (void)renderDashboardSection {
    if ([self shouldShowSetupCard]) {
        [self.contentStack addArrangedSubview:[self constrainedContentView:[self setupChecklistCard]]];
    }
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self metricsRow]]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self accountsTableCardWithHeight:176]]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self inspectorCardWithHeight:110 compact:YES]]];
}

- (void)renderAccountsSection {
    [self.contentStack addArrangedSubview:[self accountAndInspectorRowWithCompact:NO]];
    [self.contentStack addArrangedSubview:[self accountQuickActionsCard]];
}

- (void)renderQuotaSection {
    [self.contentStack addArrangedSubview:[self metricsRow]];
    [self.contentStack addArrangedSubview:[self quotaCard]];
}

- (void)renderConfigSection {
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self configCardsRow]]];
    [self.contentStack addArrangedSubview:[self constrainedContentView:[self strategyCard]]];
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
    return !CPBool(self.statusSnapshot[@"enabled"]);
}

- (NSView *)setupChecklistCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintGreaterThanOrEqualToConstant:132].active = YES;

    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];

    [stack addArrangedSubview:[self labelWithText:@"首次使用检查" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];

    BOOL runtimeReady = CPBool(self.statusSnapshot[@"runtime_exists"]) && CPBool(self.statusSnapshot[@"resource_runtime_exists"]);
    BOOL cliReady = CPBool(self.statusSnapshot[@"codex_cli_found"]);
    BOOL serviceReady = CPBool(self.statusSnapshot[@"installed"]) && CPBool(self.statusSnapshot[@"loaded"]);
    BOOL proxyReady = CPBool(self.statusSnapshot[@"enabled"]);
    NSString *cliDetail = cliReady
        ? CPDisplayString(self.statusSnapshot[@"codex_cli"])
        : CPDisplayString(self.statusSnapshot[@"codex_cli_error"]);
    NSString *serviceDetail = serviceReady ? @"后台服务已运行" : @"点击“启动/修复”安装并启动";
    NSString *proxyDetail = proxyReady ? @"Codex 已配置为代理模式" : @"点击“启用代理”写入 Codex 配置";

    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"运行资源" detail:runtimeReady ? @"运行目录已准备" : @"正在准备或缺少 App 内置资源" ok:runtimeReady]];
    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"Codex" detail:cliDetail ok:cliReady]];
    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"后台服务" detail:serviceDetail ok:serviceReady]];
    [stack addArrangedSubview:[self setupStatusLineWithTitle:@"代理配置" detail:proxyDetail ok:proxyReady]];
    return card;
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
    row.spacing = 8;
    row.distribution = NSStackViewDistributionFillEqually;
    row.translatesAutoresizingMaskIntoConstraints = NO;

    NSString *running = CPBool(self.statusSnapshot[@"running"]) ? @"在线" : @"离线";
    NSColor *runningColor = CPBool(self.statusSnapshot[@"running"]) ? NSColor.systemGreenColor : NSColor.systemRedColor;
    NSString *accounts = [NSString stringWithFormat:@"%@ / %@",
                          CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                          CPDisplayString(self.statusSnapshot[@"total_accounts"])];
    NSString *strategy = CPDisplayString(self.statusSnapshot[@"strategy"]);
    if ([strategy isEqualToString:@"-"]) {
        strategy = CPBool(self.statusSnapshot[@"running"]) ? @"轮询" : @"-";
    }
    strategy = [self strategyTitleForValue:strategy];
    [row addArrangedSubview:[self metricCardWithTitle:@"代理状态" value:running detail:@"127.0.0.1:8800" color:runningColor]];
    [row addArrangedSubview:[self metricCardWithTitle:@"可用账号" value:accounts detail:@"active / total" color:NSColor.systemBlueColor]];
    [row addArrangedSubview:[self metricCardWithTitle:@"选择策略" value:strategy detail:@"配置热更新" color:NSColor.systemPurpleColor]];
    return row;
}

- (NSString *)strategyTitleForValue:(NSString *)value {
    if ([value isEqualToString:@"round_robin"]) {
        return @"轮询";
    }
    if ([value isEqualToString:@"most_available"]) {
        return @"额度优先";
    }
    return CPDisplayString(value);
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
    [header addArrangedSubview:[self smallButtonWithTitle:@"额度" symbol:@"chart.bar" selector:@selector(refreshQuotaAction:)]];
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
    [stack addArrangedSubview:[self labelWithText:@"选中账号后，右侧检查器会直接执行启用/禁用、刷新令牌、解除冷却和删除。新增账号可以生成登录命令，也可以直接打开登录页。" font:[NSFont systemFontOfSize:13 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor]];
    NSStackView *buttons = [[NSStackView alloc] init];
    buttons.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    buttons.spacing = 8;
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"复制登录命令" symbol:@"doc.on.doc" selector:@selector(loginCommandAction:) primary:NO]];
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"打开登录页" symbol:@"person.crop.circle.badge.plus" selector:@selector(startLoginAction:) primary:NO]];
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"导入当前账号" symbol:@"square.and.arrow.down" selector:@selector(importCurrentAction:) primary:NO]];
    [stack addArrangedSubview:buttons];
    return card;
}

- (NSView *)quotaCard {
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintGreaterThanOrEqualToConstant:150].active = YES;
    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 12, 12)];

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    [header addArrangedSubview:[self labelWithText:@"额度与轮询" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [header addArrangedSubview:[self smallButtonWithTitle:@"刷新额度" symbol:@"arrow.clockwise.circle" selector:@selector(refreshQuotaAction:)]];
    [stack addArrangedSubview:header];

    for (NSDictionary *account in self.accounts) {
        NSString *name = CPString(account[@"name"]);
        NSStackView *row = [[NSStackView alloc] init];
        row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        row.alignment = NSLayoutAttributeCenterY;
        row.spacing = 8;
        NSTextField *nameLabel = [self labelWithText:CPDisplayString(name) font:[NSFont systemFontOfSize:12 weight:NSFontWeightSemibold] color:NSColor.labelColor];
        [nameLabel.widthAnchor constraintEqualToConstant:58].active = YES;
        [row addArrangedSubview:nameLabel];
        NSProgressIndicator *primary = [self progressWithValue:[self quotaRemainingForAccountName:name weekly:NO]];
        NSProgressIndicator *secondary = [self progressWithValue:[self quotaRemainingForAccountName:name weekly:YES]];
        [row addArrangedSubview:[self quotaGroupWithTitle:@"5h" progress:primary value:[self quotaTextForAccountName:name weekly:NO]]];
        [row addArrangedSubview:[self quotaGroupWithTitle:@"7d" progress:secondary value:[self quotaTextForAccountName:name weekly:YES]]];
        [stack addArrangedSubview:row];
    }
    if (!self.accounts.count) {
        [stack addArrangedSubview:[self emptyStateLabel:@"没有发现账号。请先添加账号或扫描账号目录。"]];
    }
    return card;
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
    [row addArrangedSubview:[self metricCardWithTitle:@"Codex 模式"
                                                value:[self codexModeTitle]
                                               detail:[self codexModeDetail]
                                                color:CPBool(self.statusSnapshot[@"enabled"]) ? NSColor.systemBlueColor : NSColor.systemOrangeColor]];
    [row addArrangedSubview:[self metricCardWithTitle:@"LaunchAgent"
                                                value:[self launchAgentTitle]
                                               detail:[self launchAgentDetail]
                                                color:[self launchAgentColor]]];
    [row addArrangedSubview:[self metricCardWithTitle:@"修复建议"
                                                value:CPBool(self.statusSnapshot[@"needs_repair"]) ? @"需要修复" : @"正常"
                                               detail:CPBool(self.statusSnapshot[@"needs_repair"]) ? @"后台服务路径不一致" : @"后台服务路径"
                                                color:CPBool(self.statusSnapshot[@"needs_repair"]) ? NSColor.systemRedColor : NSColor.systemGreenColor]];
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

    NSSegmentedControl *control = [[NSSegmentedControl alloc] init];
    control.segmentCount = 2;
    [control setLabel:@"轮询" forSegment:0];
    [control setLabel:@"额度优先" forSegment:1];
    control.trackingMode = NSSegmentSwitchTrackingSelectOne;
    control.target = self;
    control.action = @selector(strategyAction:);
    control.translatesAutoresizingMaskIntoConstraints = NO;
    control.controlSize = NSControlSizeSmall;
    [control.widthAnchor constraintEqualToConstant:180].active = YES;
    NSString *strategy = CPString(self.statusSnapshot[@"strategy"]);
    control.selectedSegment = [strategy isEqualToString:@"most_available"] ? 1 : 0;
    [header addArrangedSubview:control];
    [stack addArrangedSubview:header];

    NSString *detail = [NSString stringWithFormat:@"当前策略：%@。切换后立即写入配置，下次账号选择即生效。",
                        [self strategyTitleForValue:strategy.length ? strategy : @"round_robin"]];
    NSTextField *detailLabel = [self emptyStateLabel:detail];
    [stack addArrangedSubview:detailLabel];
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
    [stack addArrangedSubview:[self labelWithText:@"配置与路径" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"Codex CLI" value:CPBool(self.statusSnapshot[@"codex_cli_found"]) ? CPDisplayString(self.statusSnapshot[@"codex_cli"]) : @"未找到"]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"运行目录" value:CPDisplayString(self.statusSnapshot[@"runtime_dir"])]];
    [stack addArrangedSubview:[self infoRowWithTitle:@"源码/资源" value:CPDisplayString(self.statusSnapshot[@"source_dir"])]];
    NSStackView *buttons = [[NSStackView alloc] init];
    buttons.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    buttons.spacing = 6;
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"启用代理" symbol:@"checkmark.shield" selector:@selector(enableProxyAction:) primary:NO]];
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"Codex 直连" symbol:@"bolt.slash" selector:@selector(disableProxyAction:) primary:NO]];
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"应用更新" symbol:@"arrow.down.app" selector:@selector(applyUpdateAction:) primary:NO]];
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"路径与依赖" symbol:@"folder" selector:@selector(showPathsAction:) primary:NO]];
    [stack addArrangedSubview:buttons];
    return card;
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
    NSStackView *buttons = [[NSStackView alloc] init];
    buttons.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    buttons.spacing = 6;
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"打开日志" symbol:@"doc.text.magnifyingglass" selector:@selector(openLogAction:) primary:NO]];
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"打开结果文件" symbol:@"doc" selector:@selector(openResultAction:) primary:NO]];
    [buttons addArrangedSubview:[self actionButtonWithTitle:@"查看路径与依赖" symbol:@"folder.badge.gearshape" selector:@selector(showPathsAction:) primary:NO]];
    [stack addArrangedSubview:buttons];
    return card;
}

- (NSView *)logCardWithHeight:(CGFloat)height {
    return [self logCardWithHeight:height actions:NO];
}

- (NSView *)logCardWithHeight:(CGFloat)height actions:(BOOL)actions {
    NSView *card = [self cardViewWithBackground:NSColor.textBackgroundColor];
    card.wantsLayer = YES;
    card.layer.backgroundColor = NSColor.textBackgroundColor.CGColor;
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
    if (actions) {
        [header addArrangedSubview:[self smallButtonWithTitle:@"日志" symbol:@"doc.text.magnifyingglass" selector:@selector(openLogAction:)]];
        [header addArrangedSubview:[self smallButtonWithTitle:@"结果" symbol:@"doc" selector:@selector(openResultAction:)]];
        [header addArrangedSubview:[self smallButtonWithTitle:@"路径" symbol:@"folder.badge.gearshape" selector:@selector(showPathsAction:)]];
    }
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
    NSView *card = [self cardViewWithBackground:NSColor.textBackgroundColor];
    card.wantsLayer = YES;
    card.layer.backgroundColor = NSColor.textBackgroundColor.CGColor;
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintEqualToConstant:320].active = YES;

    NSStackView *stack = [[NSStackView alloc] init];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeWidth;
    stack.spacing = 8;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [card addSubview:stack];
    [self pinView:stack toView:card insets:NSEdgeInsetsMake(12, 12, 10, 12)];

    NSStackView *header = [[NSStackView alloc] init];
    header.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    header.alignment = NSLayoutAttributeCenterY;
    header.spacing = 6;
    [header addArrangedSubview:[self labelWithText:@"最近请求" font:[NSFont systemFontOfSize:16 weight:NSFontWeightBold] color:NSColor.labelColor]];
    NSView *flex = [[NSView alloc] init];
    [header addArrangedSubview:flex];
    [header addArrangedSubview:[self smallButtonWithTitle:@"清空" symbol:@"trash" selector:@selector(clearRecentRequestsAction:)]];
    [header addArrangedSubview:[self smallButtonWithTitle:@"刷新" symbol:@"arrow.clockwise" selector:@selector(refreshSnapshots:)]];
    [header addArrangedSubview:[self smallButtonWithTitle:@"路径" symbol:@"folder.badge.gearshape" selector:@selector(showPathsAction:)]];
    [stack addArrangedSubview:header];

    NSView *table = [[NSView alloc] init];
    table.wantsLayer = YES;
    table.layer.backgroundColor = NSColor.controlBackgroundColor.CGColor;
    table.translatesAutoresizingMaskIntoConstraints = NO;
    [table.heightAnchor constraintGreaterThanOrEqualToConstant:248].active = YES;
    [stack addArrangedSubview:table];
    [table.widthAnchor constraintEqualToAnchor:stack.widthAnchor].active = YES;

    NSStackView *rows = [[NSStackView alloc] init];
    rows.orientation = NSUserInterfaceLayoutOrientationVertical;
    rows.alignment = NSLayoutAttributeWidth;
    rows.spacing = 0;
    rows.translatesAutoresizingMaskIntoConstraints = NO;
    [table addSubview:rows];
    [self pinView:rows toView:table insets:NSEdgeInsetsMake(0, 0, 0, 0)];

    NSView *head = [self recentRequestRowWithTime:@"时间" account:@"账号" status:@"状态" path:@"路径" header:YES];
    [rows addArrangedSubview:head];
    [head.widthAnchor constraintEqualToAnchor:rows.widthAnchor].active = YES;
    NSArray *items = CPArray(self.statusSnapshot[@"recent_requests"]);
    NSInteger count = MIN((NSInteger)items.count, 9);
    for (NSInteger i = 0; i < count; i++) {
        NSDictionary *item = CPDict(items[i]);
        NSView *row = [self recentRequestRowWithTime:[self requestTimeText:item[@"at"]]
                                             account:CPDisplayString(item[@"account"])
                                              status:CPDisplayString(item[@"status"])
                                                path:CPDisplayString(item[@"path"])
                                              header:NO];
        [rows addArrangedSubview:row];
        [row.widthAnchor constraintEqualToAnchor:rows.widthAnchor].active = YES;
    }
    if (count == 0) {
        NSTextField *empty = [self emptyStateLabel:@"暂无最近请求。代理收到请求后会显示在这里。"];
        [rows addArrangedSubview:empty];
        [empty.widthAnchor constraintEqualToAnchor:rows.widthAnchor].active = YES;
    }
    return card;
}

- (NSView *)recentRequestRowWithTime:(NSString *)time account:(NSString *)account status:(NSString *)status path:(NSString *)path header:(BOOL)header {
    NSView *row = [[NSView alloc] init];
    row.translatesAutoresizingMaskIntoConstraints = NO;
    [row.heightAnchor constraintEqualToConstant:header ? 24 : 25].active = YES;

    NSTextField *timeLabel = [self labelWithText:time font:[NSFont monospacedSystemFontOfSize:10 weight:header ? NSFontWeightSemibold : NSFontWeightRegular] color:header ? NSColor.secondaryLabelColor : NSColor.labelColor];
    NSTextField *accountLabel = [self labelWithText:account font:[NSFont monospacedSystemFontOfSize:10 weight:header ? NSFontWeightSemibold : NSFontWeightRegular] color:header ? NSColor.secondaryLabelColor : NSColor.labelColor];
    NSTextField *statusLabel = [self labelWithText:status font:[NSFont monospacedSystemFontOfSize:10 weight:header ? NSFontWeightSemibold : NSFontWeightRegular] color:[status hasPrefix:@"2"] ? NSColor.systemGreenColor : (header ? NSColor.secondaryLabelColor : NSColor.systemOrangeColor)];
    NSTextField *pathLabel = [self labelWithText:path font:[NSFont monospacedSystemFontOfSize:9 weight:NSFontWeightRegular] color:header ? NSColor.secondaryLabelColor : NSColor.secondaryLabelColor];
    timeLabel.alignment = NSTextAlignmentLeft;
    accountLabel.alignment = NSTextAlignmentLeft;
    statusLabel.alignment = NSTextAlignmentCenter;
    pathLabel.alignment = NSTextAlignmentLeft;
    pathLabel.lineBreakMode = NSLineBreakByTruncatingMiddle;
    [row addSubview:timeLabel];
    [row addSubview:accountLabel];
    [row addSubview:statusLabel];
    [row addSubview:pathLabel];
    [NSLayoutConstraint activateConstraints:@[
        [timeLabel.leadingAnchor constraintEqualToAnchor:row.leadingAnchor constant:8],
        [timeLabel.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
        [timeLabel.widthAnchor constraintEqualToConstant:54],

        [accountLabel.leadingAnchor constraintEqualToAnchor:row.leadingAnchor constant:66],
        [accountLabel.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
        [accountLabel.widthAnchor constraintEqualToConstant:30],

        [statusLabel.leadingAnchor constraintEqualToAnchor:row.leadingAnchor constant:106],
        [statusLabel.centerYAnchor constraintEqualToAnchor:row.centerYAnchor],
        [statusLabel.widthAnchor constraintEqualToConstant:30],

        [pathLabel.leadingAnchor constraintEqualToAnchor:row.leadingAnchor constant:148],
        [pathLabel.trailingAnchor constraintEqualToAnchor:row.trailingAnchor constant:-8],
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
    return [self cardViewWithBackground:NSColor.controlBackgroundColor];
}

- (NSView *)cardViewWithBackground:(NSColor *)background {
    NSView *view = [[NSView alloc] init];
    view.wantsLayer = YES;
    view.layer.cornerRadius = 8;
    view.layer.backgroundColor = background.CGColor;
    view.layer.borderColor = NSColor.separatorColor.CGColor;
    view.layer.borderWidth = 0.5;
    view.layer.shadowColor = NSColor.blackColor.CGColor;
    view.layer.shadowOpacity = 0.04;
    view.layer.shadowOffset = CGSizeMake(0, -1);
    view.layer.shadowRadius = 4;
    return view;
}

- (NSView *)statusDotWithColor:(NSColor *)color {
    NSView *dot = [[NSView alloc] init];
    dot.translatesAutoresizingMaskIntoConstraints = NO;
    dot.wantsLayer = YES;
    dot.layer.cornerRadius = 4;
    dot.layer.backgroundColor = color.CGColor;
    [dot.widthAnchor constraintEqualToConstant:8].active = YES;
    [dot.heightAnchor constraintEqualToConstant:8].active = YES;
    return dot;
}

- (NSButton *)navigationButtonWithTitle:(NSString *)title symbol:(NSString *)symbol tag:(NSInteger)tag {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:@selector(navigationAction:)];
    button.tag = tag;
    button.bordered = NO;
    button.alignment = NSTextAlignmentLeft;
    button.imagePosition = NSImageLeading;
    button.contentTintColor = NSColor.labelColor;
    button.font = [NSFont systemFontOfSize:13 weight:NSFontWeightSemibold];
    button.translatesAutoresizingMaskIntoConstraints = NO;
    button.wantsLayer = YES;
    button.layer.cornerRadius = 7;
    NSImage *image = [self symbolImageNamed:symbol];
    if (image) {
        button.image = image;
    }
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
    NSImage *image = [self symbolImageNamed:symbol];
    if (image) {
        button.image = image;
    }
    [button.heightAnchor constraintEqualToConstant:28].active = YES;
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
            image.accessibilityDescription = @"Codex Proxy 控制台";
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
        imageView.accessibilityLabel = @"Codex Proxy 控制台";
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
    NSView *card = [self cardView];
    card.translatesAutoresizingMaskIntoConstraints = NO;
    [card.heightAnchor constraintEqualToConstant:84].active = YES;
    [card.widthAnchor constraintGreaterThanOrEqualToConstant:112].active = YES;

    NSTextField *titleLabel = [self labelWithText:title font:[NSFont systemFontOfSize:10 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor];
    NSTextField *valueLabel = [self labelWithText:value ?: @"-" font:[NSFont systemFontOfSize:20 weight:NSFontWeightBold] color:color ?: NSColor.labelColor];
    NSTextField *detailLabel = [self labelWithText:detail ?: @"" font:[NSFont systemFontOfSize:10 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
    for (NSTextField *label in @[titleLabel, valueLabel, detailLabel]) {
        label.alignment = NSTextAlignmentCenter;
        label.maximumNumberOfLines = 1;
        label.lineBreakMode = NSLineBreakByTruncatingTail;
        [label setContentCompressionResistancePriority:NSLayoutPriorityDefaultHigh forOrientation:NSLayoutConstraintOrientationVertical];
        [card addSubview:label];
    }
    [NSLayoutConstraint activateConstraints:@[
        [titleLabel.leadingAnchor constraintEqualToAnchor:card.leadingAnchor constant:6],
        [titleLabel.trailingAnchor constraintEqualToAnchor:card.trailingAnchor constant:-6],
        [titleLabel.topAnchor constraintEqualToAnchor:card.topAnchor constant:10],
        [titleLabel.heightAnchor constraintEqualToConstant:16],

        [valueLabel.leadingAnchor constraintEqualToAnchor:card.leadingAnchor constant:4],
        [valueLabel.trailingAnchor constraintEqualToAnchor:card.trailingAnchor constant:-4],
        [valueLabel.centerYAnchor constraintEqualToAnchor:card.centerYAnchor constant:0],
        [valueLabel.heightAnchor constraintEqualToConstant:30],

        [detailLabel.leadingAnchor constraintEqualToAnchor:card.leadingAnchor constant:6],
        [detailLabel.trailingAnchor constraintEqualToAnchor:card.trailingAnchor constant:-6],
        [detailLabel.bottomAnchor constraintEqualToAnchor:card.bottomAnchor constant:-9],
        [detailLabel.heightAnchor constraintEqualToConstant:16],
    ]];
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

- (NSProgressIndicator *)progressWithValue:(double)value {
    NSProgressIndicator *progress = [[NSProgressIndicator alloc] init];
    progress.indeterminate = NO;
    progress.minValue = 0;
    progress.maxValue = 100;
    progress.doubleValue = MAX(0, MIN(100, value));
    progress.controlSize = NSControlSizeSmall;
    progress.translatesAutoresizingMaskIntoConstraints = NO;
    [progress.widthAnchor constraintEqualToConstant:140].active = YES;
    return progress;
}

- (NSView *)quotaGroupWithTitle:(NSString *)title progress:(NSProgressIndicator *)progress value:(NSString *)value {
    NSStackView *group = [[NSStackView alloc] init];
    group.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    group.spacing = 8;
    group.alignment = NSLayoutAttributeCenterY;
    [group addArrangedSubview:[self labelWithText:title font:[NSFont systemFontOfSize:12 weight:NSFontWeightMedium] color:NSColor.secondaryLabelColor]];
    [group addArrangedSubview:progress];
    [group addArrangedSubview:[self labelWithText:value font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor]];
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

- (void)refreshSnapshots:(id)sender {
    if (self.busy) {
        return;
    }
    [self setBusy:YES message:@"正在刷新状态..."];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSDictionary *localStatus = [self runPythonJSONSync:@[@"status"] rawText:nil];
        NSDictionary *remoteStatus = [self fetchJSONPath:@"/api/status" method:@"GET" timeout:2.0];
        BOOL proxyOnline = [remoteStatus isKindOfClass:NSDictionary.class] && CPBool(remoteStatus[@"running"]);
        NSMutableDictionary *mergedStatus = [localStatus isKindOfClass:NSDictionary.class] ? [localStatus mutableCopy] : [NSMutableDictionary dictionary];
        if (proxyOnline) {
            [mergedStatus addEntriesFromDictionary:remoteStatus];
        } else if (!mergedStatus.count) {
            mergedStatus[@"running"] = @NO;
        }
        NSDictionary *status = mergedStatus;

        NSArray *accounts = @[];
        NSDictionary *quota = @{};
        if (proxyOnline) {
            id remoteAccounts = [self fetchJSONPath:@"/api/accounts" method:@"GET" timeout:2.0];
            if ([remoteAccounts isKindOfClass:NSArray.class]) {
                accounts = remoteAccounts;
            }
            id remoteQuota = [self fetchJSONPath:@"/api/quota" method:@"GET" timeout:2.0];
            if ([remoteQuota isKindOfClass:NSDictionary.class]) {
                quota = remoteQuota;
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

        dispatch_async(dispatch_get_main_queue(), ^{
            self.statusSnapshot = status ?: @{};
            self.accounts = accounts ?: @[];
            self.quotaSnapshot = quota ?: @{};
            if (!self.selectedAccountName.length && self.accounts.count) {
                self.selectedAccountName = CPString(self.accounts.firstObject[@"name"]);
            }
            [self updateStatusViews];
            [self renderActiveSection];
            [self setBusy:NO message:@"状态已刷新"];
        });
    });
}

- (void)refreshQuotaAction:(id)sender {
    if (!CPBool(self.statusSnapshot[@"running"])) {
        [self appendLog:@"代理离线，无法主动刷新远端额度；已显示本地账号状态。"];
        self.footerStatusLabel.stringValue = @"代理离线，无法刷新额度";
        return;
    }
    [self setBusy:YES message:@"正在刷新额度..."];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSDictionary *result = [self fetchJSONPath:@"/api/quota/refresh" method:@"POST" timeout:12.0];
        NSDictionary *localStatus = [self runPythonJSONSync:@[@"status"] rawText:nil];
        id remoteStatus = [self fetchJSONPath:@"/api/status" method:@"GET" timeout:2.0];
        id remoteAccounts = [self fetchJSONPath:@"/api/accounts" method:@"GET" timeout:2.0];
        id remoteQuota = [self fetchJSONPath:@"/api/quota" method:@"GET" timeout:2.0];
        dispatch_async(dispatch_get_main_queue(), ^{
            NSDictionary *accounts = CPDict(result[@"accounts"]);
            NSInteger refreshed = 0;
            NSInteger failed = 0;
            for (id key in accounts) {
                NSDictionary *item = CPDict(accounts[key]);
                if (CPBool(item[@"refreshed"])) {
                    refreshed += 1;
                } else {
                    failed += 1;
                }
            }
            NSString *message = result
                ? [NSString stringWithFormat:@"额度刷新完成：%ld 成功 / %ld 失败", (long)refreshed, (long)failed]
                : @"额度刷新失败：代理无响应或请求超时";
            [self appendLog:[NSString stringWithFormat:@"刷新额度\n%@", CPPrettyJSON(result ?: @{@"error": @"request failed"})]];
            NSMutableDictionary *mergedStatus = [localStatus isKindOfClass:NSDictionary.class] ? [localStatus mutableCopy] : [self.statusSnapshot mutableCopy];
            if ([remoteStatus isKindOfClass:NSDictionary.class]) {
                [mergedStatus addEntriesFromDictionary:remoteStatus];
            }
            if (mergedStatus.count) {
                self.statusSnapshot = mergedStatus;
            }
            if ([remoteAccounts isKindOfClass:NSArray.class]) {
                self.accounts = remoteAccounts;
            }
            if ([remoteQuota isKindOfClass:NSDictionary.class]) {
                self.quotaSnapshot = remoteQuota;
            }
            [self updateStatusViews];
            [self renderActiveSection];
            [self setBusy:NO message:message];
        });
    });
}

- (void)updateStatusViews {
    BOOL running = CPBool(self.statusSnapshot[@"running"]);
    NSString *online = running ? @"代理在线" : @"代理离线";
    NSString *accounts = [NSString stringWithFormat:@"%@/%@ 可用",
                          CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                          CPDisplayString(self.statusSnapshot[@"total_accounts"])];
    self.subtitleLabel.stringValue = [NSString stringWithFormat:@"%@ · %@ · %@", online, accounts, [self codexModeDetail]];
    self.sidebarStatusLabel.stringValue = [NSString stringWithFormat:@"%@ · %@/%@ 可用",
                                           running ? @"在线" : @"离线",
                                           CPDisplayString(self.statusSnapshot[@"active_accounts"]),
                                           CPDisplayString(self.statusSnapshot[@"total_accounts"])];
}

- (void)updateHeaderText {
    NSDictionary *titles = @{
        @"dashboard": @[@"总览", @"代理、账号池和运行状态。"],
        @"config": @[@"配置", @"检查 LaunchAgent、代理模式和策略。"],
        @"logs": @[@"日志", @"查看操作结果、日志和路径诊断。"],
    };
    NSArray *pair = titles[self.activeSection] ?: titles[@"dashboard"];
    self.titleLabel.stringValue = pair[0];
    BOOL running = CPBool(self.statusSnapshot[@"running"]);
    NSString *state = running ? @"代理在线" : @"代理离线";
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
    if (self.busy) {
        return;
    }
    [self setBusy:YES message:[NSString stringWithFormat:@"正在执行：%@...", label]];
    [self appendLog:[NSString stringWithFormat:@"$ %@", label]];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSString *raw = nil;
        NSDictionary *result = [self runPythonJSONSync:args rawText:&raw];
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

- (void)repairAction:(id)sender {
    [self performAction:@[@"repair"] label:@"启动/修复" refreshAfter:YES];
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
    [self performAction:@[@"repair-open-codex"] label:@"打开 Codex" refreshAfter:YES];
}

- (void)openWebAction:(id)sender {
    [self performAction:@[@"repair-open-web"] label:@"打开网页状态页" refreshAfter:YES];
}

- (void)strategyAction:(NSSegmentedControl *)sender {
    NSString *strategy = sender.selectedSegment == 1 ? @"most_available" : @"round_robin";
    [self performAction:@[@"set-rotation-strategy", @"--strategy", strategy]
                  label:[NSString stringWithFormat:@"切换选择策略为 %@", [self strategyTitleForValue:strategy]]
           refreshAfter:YES];
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
    return [self copyRuntimeResourcesForce:NO error:error];
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
        if (dstExists && !force) {
            continue;
        }
        if (dstExists && force && ![fm removeItemAtPath:dst error:error]) {
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
    NSString *script = [self.resourceRuntimeDir stringByAppendingPathComponent:@"control_actions.py"];
    NSDictionary *environment = [self taskEnvironmentForSourceDir:self.resourceRuntimeDir
                                               includeProxyPython:NO
                                                fallbackToRuntime:NO];
    return [self runPythonJSONSyncWithScript:script
                            workingDirectory:self.resourceRuntimeDir
                                  executable:[self pythonExecutablePreferRuntime:NO]
                                        args:@[@"apply-update"]
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
    NSString *content = [NSString stringWithFormat:@"Codex 代理控制台\n操作：%@\n时间：%@\n\n%@\n\n日志：%@\n",
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
        self.footerStatusLabel.stringValue = message ?: @"";
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
        NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
        formatter.dateFormat = @"HH:mm:ss";
        NSString *stamp = [formatter stringFromDate:NSDate.date];
        NSString *line = [NSString stringWithFormat:@"[%@] %@\n", stamp, text ?: @""];
        NSString *old = self.outputView.string ?: @"";
        self.outputView.string = [old stringByAppendingString:line];
        [self.outputView scrollToEndOfDocument:nil];
    });
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

- (void)rebuildInspector {
    if (!self.inspectorStack) {
        return;
    }
    NSArray *oldViews = self.inspectorStack.arrangedSubviews.copy;
    for (NSView *view in oldViews) {
        [self.inspectorStack removeArrangedSubview:view];
        [view removeFromSuperview];
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

        NSString *summary = [NSString stringWithFormat:@"%@ · %@ · %@ · %@",
                             name,
                             [self stateLabelForAccount:account],
                             [self quotaResetTextForAccountName:CPString(account[@"name"]) weekly:NO],
                             [self quotaResetTextForAccountName:CPString(account[@"name"]) weekly:YES]];
        NSTextField *summaryLabel = [self labelWithText:summary font:[NSFont systemFontOfSize:12 weight:NSFontWeightRegular] color:NSColor.secondaryLabelColor];
        summaryLabel.lineBreakMode = NSLineBreakByTruncatingMiddle;
        [self.inspectorStack addArrangedSubview:summaryLabel];

        NSStackView *buttonRow = [[NSStackView alloc] init];
        buttonRow.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        buttonRow.spacing = 6;
        [buttonRow addArrangedSubview:[self smallButtonWithTitle:@"刷新令牌" symbol:@"key" selector:@selector(refreshTokenAction:)]];
        [buttonRow addArrangedSubview:[self smallButtonWithTitle:CPBool(account[@"enabled"]) ? @"禁用" : @"启用" symbol:@"power" selector:@selector(toggleAccountAction:)]];
        [buttonRow addArrangedSubview:[self smallButtonWithTitle:@"解除冷却" symbol:@"timer" selector:@selector(clearCooldownAction:)]];
        [buttonRow addArrangedSubview:[self smallButtonWithTitle:@"删除" symbol:@"trash" selector:@selector(deleteAccountAction:)]];
        [self.inspectorStack addArrangedSubview:buttonRow];
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
    NSDate *date = [NSDate dateWithTimeIntervalSince1970:fetchedAt];
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.dateFormat = @"MM-dd HH:mm";
    return [NSString stringWithFormat:@"刷新 %@", [formatter stringFromDate:date] ?: @"-"];
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
    NSDate *date = [NSDate dateWithTimeIntervalSince1970:resetAt];
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.dateFormat = @"MM-dd HH:mm";
    return [NSString stringWithFormat:@"%@刷新 %@", prefix, [formatter stringFromDate:date] ?: @"-"];
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
    NSArray *ids = @[@"dashboard", @"config", @"logs"];
    if (sender.tag >= 0 && sender.tag < ids.count) {
        self.activeSection = ids[sender.tag];
        [self updateNavigationSelection];
        [self renderActiveSection];
    }
}

- (void)updateNavigationSelection {
    NSArray *ids = @[@"dashboard", @"config", @"logs"];
    for (NSButton *button in self.navButtons) {
        BOOL selected = button.tag >= 0 && button.tag < ids.count && [ids[button.tag] isEqualToString:self.activeSection];
        button.state = selected ? NSControlStateValueOn : NSControlStateValueOff;
        button.layer.backgroundColor = selected ? [NSColor.selectedContentBackgroundColor colorWithAlphaComponent:0.16].CGColor : NSColor.clearColor.CGColor;
        button.contentTintColor = selected ? NSColor.controlAccentColor : NSColor.labelColor;
    }
}

@end

@interface AppDelegate : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) ControlWindowController *controller;
@end

@implementation AppDelegate
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.controller = [[ControlWindowController alloc] init];
    [self.controller show];
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return YES;
}
@end

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        AppDelegate *delegate = [[AppDelegate alloc] init];
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        [app run];
    }
    return 0;
}
