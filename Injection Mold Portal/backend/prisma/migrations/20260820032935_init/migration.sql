-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "email" TEXT NOT NULL,
    "passwordHash" TEXT NOT NULL,
    "companyName" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'customer',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "Order" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "partName" TEXT NOT NULL,
    "materialId" TEXT NOT NULL,
    "partWeightG" REAL NOT NULL,
    "wallThicknessMm" REAL NOT NULL,
    "quantity" INTEGER NOT NULL,
    "cavities" INTEGER NOT NULL,
    "tolerance" TEXT NOT NULL,
    "finish" TEXT NOT NULL,
    "color" TEXT NOT NULL,
    "newTool" BOOLEAN NOT NULL,
    "amortizeTooling" BOOLEAN NOT NULL,
    "unitPrice" REAL NOT NULL,
    "partsSubtotal" REAL NOT NULL,
    "toolingCost" REAL NOT NULL,
    "toolingAmortized" BOOLEAN NOT NULL,
    "grandTotal" REAL NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'USD',
    "estimatedCycleTimeSec" REAL NOT NULL,
    "estimatedLeadTimeDays" INTEGER NOT NULL,
    "breakdownJson" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'quote_requested',
    "paymentStatus" TEXT NOT NULL DEFAULT 'unpaid',
    "stripeSessionId" TEXT,
    "stripePaymentIntentId" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "Order_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "CadFile" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "orderId" TEXT NOT NULL,
    "filename" TEXT NOT NULL,
    "storedPath" TEXT NOT NULL,
    "volumeCm3" REAL NOT NULL,
    "surfaceAreaCm2" REAL NOT NULL,
    "bboxXMm" REAL NOT NULL,
    "bboxYMm" REAL NOT NULL,
    "bboxZMm" REAL NOT NULL,
    "triangleCount" INTEGER NOT NULL,
    "uploadedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "CadFile_orderId_fkey" FOREIGN KEY ("orderId") REFERENCES "Order" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "CadFile_orderId_key" ON "CadFile"("orderId");
